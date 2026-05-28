from __future__ import annotations

from typing import Annotated, Any, Callable

from langgraph.graph import END, START, StateGraph
from omegaconf import DictConfig
from typing_extensions import TypedDict

from src.context import AppContext
from src.gpt_extraction.graph_condition import evaluate_condition
from src.gpt_extraction.pdf_parse_gpt_bridge import PdfParseGptBridge
from src.utils.config import read_config
from src.utils.step import Step

_START = "__start__"
_END = "__end__"


def _merge_extractions(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    a = dict(left) if left else {}
    b = dict(right) if right else {}
    return {**a, **b}


class PdfParseLlmState(TypedDict, total=False):
    page_texts: list[str]
    extractions: Annotated[dict[str, Any], _merge_extractions]


def normalize_page_texts(page_texts: str | list[str]) -> list[str]:
    """
    Coerce orchestrator input into graph state.

    Callers may pass per-page strings (preferred) or a single joined document string.
    """
    if isinstance(page_texts, str):
        return [page_texts] if page_texts else []
    return list(page_texts)


def _as_node_list(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        return [value]
    return list(value)


def _normalize_endpoint(name: str) -> str:
    if name in (_START, "START"):
        return _START
    if name in (_END, "END"):
        return _END
    return name


class BuildGraph(Step):
    """
    Build and run a LangGraph pipeline from ``config.graph`` (``configs/graph.yml``).

    Uses :class:`~src.gpt_extraction.pdf_parse_gpt_bridge.PdfParseGptBridge` for
  ``run_one_sync`` / ``aux_parallel_extractions``.

    **nodes** — one schema per leaf; optional ``when`` expression.
    **parallel** — named groups of leaf ids (e.g. ``extract_pages_parallel``).
    **edges** — ``to: <parallel_name>`` enters a parallel group.
    **conditional_edges** — ``from: <parallel_name>`` after the group completes.
    """

    def __init__(
        self,
        context: AppContext,
        config: DictConfig,
        bridge: PdfParseGptBridge | None = None,
    ) -> None:
        super().__init__(config, context)
        self._bridge = bridge or PdfParseGptBridge(context, config)
        self._graph_cfg = self._config.graph
        self._leaf_handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self._parallel_groups: dict[str, list[str]] = self._load_parallel_groups()

    @classmethod
    def from_config_dir(
        cls,
        config_path: str = "./configs",
        *,
        context: AppContext | None = None,
        bridge: PdfParseGptBridge | None = None,
    ) -> BuildGraph:
        """Load merged YAML config (:func:`src.utils.config.read_config`) and build."""
        config = read_config(config_path)
        ctx = context or AppContext(config=config)
        return cls(ctx, config, bridge=bridge)

    def _load_parallel_groups(self) -> dict[str, list[str]]:
        raw = self._graph_cfg.get("parallel") or {}
        groups: dict[str, list[str]] = {}
        for group_id, children in raw.items():
            child_list = list(children or [])
            if not child_list:
                raise ValueError(f"parallel.{group_id!r} must list at least one node")
            groups[str(group_id)] = [str(c) for c in child_list]
        return groups

    def _validate_parallel_groups(self, nodes_cfg: dict[str, Any]) -> None:
        for group_id, children in self._parallel_groups.items():
            for child in children:
                if child not in nodes_cfg:
                    raise ValueError(
                        f"parallel.{group_id!r} references unknown node {child!r}"
                    )
            if group_id in nodes_cfg:
                raise ValueError(
                    f"parallel group {group_id!r} must not duplicate a leaf node name"
                )

    def build(self):
        """Compile and return the LangGraph runnable."""
        nodes_cfg: dict[str, Any] = self._graph_cfg.get("nodes") or {}
        if not nodes_cfg:
            raise ValueError("graph.nodes is empty; check configs/graph.yml")

        self._validate_parallel_groups(nodes_cfg)

        for node_id, node_def in nodes_cfg.items():
            self._leaf_handlers[node_id] = self._make_leaf_node(node_id, node_def)

        g = StateGraph(PdfParseLlmState)
        registered: set[str] = set()

        def _register(node_id: str, handler: Callable) -> None:
            if node_id not in registered:
                g.add_node(node_id, handler)
                registered.add(node_id)

        for node_id in nodes_cfg:
            _register(node_id, self._leaf_handlers[node_id])

        for group_id, children in self._parallel_groups.items():
            _register(group_id, self._make_parallel_group(group_id, children))

        for edge in self._graph_cfg.get("edges") or []:
            self._wire_edge(g, edge, _register)

        for cond in self._graph_cfg.get("conditional_edges") or []:
            self._wire_conditional_edge(g, cond)

        graph_name = self._graph_cfg.get("graph_name", "pdf_parse_llm")
        self._log.debug(
            "Compiled graph %r with %d nodes (%d parallel groups)",
            graph_name,
            len(registered),
            len(self._parallel_groups),
        )
        return g.compile()

    def run(self, page_texts: str | list[str], **kwargs: Any) -> dict[str, Any]:
        """Execute the compiled graph; return merged ``extractions`` (``Step.run``)."""
        pages = normalize_page_texts(page_texts)
        app = self.build()
        final: PdfParseLlmState = app.invoke(
            {
                "page_texts": pages,
                "extractions": {},
            }
        )
        return dict(final.get("extractions") or {})

    def _endpoint(self, name: str):
        if name in (_START, "START"):
            return START
        if name in (_END, "END"):
            return END
        return name

    def _resolve_source(self, from_value: str | list[str]) -> str:
        name = _as_node_list(from_value)[0]
        if name in self._parallel_groups:
            return name
        if isinstance(from_value, list) and len(from_value) > 1:
            raise ValueError(
                f"Fan-in from list {from_value!r} is no longer supported; "
                f"use from: <parallel_group_name> (see graph.parallel in graph.yml)"
            )
        return name

    def _is_parallel_target(self, target: str) -> bool:
        return target in self._parallel_groups

    def _wire_edge(self, g: StateGraph, edge: dict[str, Any], register) -> None:
        src_raw = edge["from"]
        dst_raw = edge["to"]
        src_key = _normalize_endpoint(
            src_raw if isinstance(src_raw, str) else src_raw[0]
        )
        dst_key = _normalize_endpoint(
            dst_raw if isinstance(dst_raw, str) else dst_raw[0]
        )

        if src_key == _START and dst_key not in (_START, _END):
            dst_nodes = _as_node_list(dst_raw)
            if len(dst_nodes) > 1:
                raise ValueError("__start__ cannot fan-out to multiple nodes directly")
            register(dst_nodes[0], self._leaf_handlers[dst_nodes[0]])
            g.add_edge(START, dst_nodes[0])
            return

        if isinstance(dst_raw, list):
            raise ValueError(
                "Inline parallel lists on edges are removed; declare "
                "graph.parallel.<name> and use to: <name>"
            )

        src = _as_node_list(src_raw)[0]
        dst = _as_node_list(dst_raw)[0]

        if self._is_parallel_target(dst):
            if dst_key == _END:
                raise ValueError("parallel group cannot be __end__")
            g.add_edge(src, dst)
            return

        if dst_key == _END:
            g.add_edge(src, END)
        else:
            if dst not in self._leaf_handlers:
                raise ValueError(
                    f"Unknown edge target {dst!r}; define it under graph.nodes "
                    f"or graph.parallel"
                )
            register(dst, self._leaf_handlers[dst])
            g.add_edge(src, dst)

    def _wire_conditional_edge(self, g: StateGraph, cond: dict[str, Any]) -> None:
        from_raw = cond["from"]
        branches = list(cond.get("branches") or [])
        if not branches:
            raise ValueError("conditional_edges entry requires branches")

        source = self._resolve_source(from_raw)
        if source not in self._parallel_groups and source not in self._leaf_handlers:
            raise ValueError(
                f"conditional_edges from {from_raw!r}: unknown source {source!r}"
            )
        paths: dict[str, Any] = {}
        else_target: str | None = None

        for i, branch in enumerate(branches):
            target = branch["to"]
            target_norm = _normalize_endpoint(target)
            if branch.get("else"):
                else_target = target
                paths["__else__"] = self._endpoint(target_norm)
                continue
            label = branch.get("label") or branch.get("name") or f"branch_{i}"
            paths[str(label)] = self._endpoint(target_norm)

        if else_target is None:
            raise ValueError(
                f"conditional_edges from {from_raw!r} needs one branch with else: true"
            )

        captured_branches = branches

        def _router(state: dict[str, Any]) -> str:
            for i, branch in enumerate(captured_branches):
                if branch.get("else"):
                    continue
                expr = branch.get("if")
                label = branch.get("label") or branch.get("name") or f"branch_{i}"
                if evaluate_condition(expr, state):
                    return str(label)
            return "__else__"

        g.add_conditional_edges(source, _router, paths)

    def _state_input(self, state: dict[str, Any], input_key: str) -> list[str]:
        texts = state.get(input_key)
        if texts is None:
            raise KeyError(f"state[{input_key!r}] is missing")
        if isinstance(texts, str):
            return normalize_page_texts(texts)
        if isinstance(texts, list):
            return list(texts)
        raise TypeError(f"state[{input_key!r}] must be str or list[str], got {type(texts)!r}")

    def _prompt_override(self, node_def: dict[str, Any]) -> tuple[str, str] | None:
        prompt = node_def.get("prompt")
        if not prompt:
            return None
        system = prompt.get("system")
        user = prompt.get("user")
        if system and user:
            return str(system), str(user)
        return None

    def _active_schemas_for_parallel(
        self, child_ids: list[str], state: dict[str, Any]
    ) -> tuple[list[str], str, str]:
        nodes_cfg: dict[str, Any] = self._graph_cfg.get("nodes") or {}
        schemas: list[str] = []
        tier = "fast"
        input_key = "page_texts"
        for cid in child_ids:
            nd = nodes_cfg[cid]
            when = nd.get("when")
            if when is not None and not evaluate_condition(when, state):
                self._log.debug("skip parallel child %s (when=false)", cid)
                continue
            schemas.append(nd["schema"])
            tier = nd.get("tier", tier)
            input_key = nd.get("input", input_key)
        return schemas, tier, input_key

    def _run_leaf(
        self, node_id: str, node_def: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any]:
        when = node_def.get("when")
        if when is not None and not evaluate_condition(when, state):
            self._log.debug("skip node %s (when=false)", node_id)
            return {"extractions": {}}

        schema = node_def["schema"]
        tier = node_def.get("tier", "fast")
        input_key = node_def.get("input", "page_texts")
        output_key = node_def.get("output_key", schema)
        page_texts = self._state_input(state, input_key)
        _, payload = self._bridge.run_one_sync(
            schema,
            page_texts,
            tier=tier,
            prompt_files=self._prompt_override(node_def),
        )
        return {"extractions": {output_key: payload}}

    def _make_leaf_node(
        self, node_id: str, node_def: dict[str, Any]
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        if "schema" not in node_def:
            raise ValueError(f"Node {node_id!r} must declare schema")

        def _node(state: dict[str, Any]) -> dict[str, Any]:
            return self._run_leaf(node_id, node_def, state)

        return _node

    def _make_parallel_group(
        self, group_id: str, child_ids: list[str]
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def _node(state: dict[str, Any]) -> dict[str, Any]:
            schemas, tier, input_key = self._active_schemas_for_parallel(
                child_ids, state
            )
            if not schemas:
                return {"extractions": {}}
            page_texts = self._state_input(state, input_key)
            return self._bridge.aux_parallel_extractions(
                tuple(schemas),
                page_texts,
                tier=tier,
            )

        return _node


def build_pdf_parse_llm_graph(
    bridge: PdfParseGptBridge,
    *,
    context: AppContext | None = None,
    config: DictConfig | None = None,
):
    """Compile a graph using an existing :class:`PdfParseGptBridge`."""
    cfg = config or bridge._config
    ctx = context or bridge._context
    return BuildGraph(ctx, cfg, bridge=bridge).build()


def run_pdf_parse_llm_graph(
    bridge: PdfParseGptBridge,
    page_texts: str | list[str],
    *,
    context: AppContext | None = None,
    config: DictConfig | None = None,
) -> dict[str, Any]:
    """Run the extraction graph; return merged ``extractions``.

    ``page_texts`` may be a per-page ``list[str]`` (from PyMuPDF) or one joined ``str``.
    """
    cfg = config or bridge._config
    ctx = context or bridge._context
    return BuildGraph(ctx, cfg, bridge=bridge).run(page_texts)
