from src.celery.tasks.parse_orchestrator import PdfParseOrchestrator
from src.gpt_extraction.pdf_parse_gpt_bridge import PdfParseGptBridge
from src.gpt_extraction.pdf_parse_llm_graph import run_pdf_parse_llm_graph
from src.celery.utils.post_process_llm_values import post_process_llm_values
from src.utils.text_llm_excel import save_parse_excel_export

from src.context import config, context
from src.constants.variables import schemas_dict
from pathlib import Path
from tqdm import tqdm
from glob import glob
import json
import numpy as np
from typing import Any

def evaluate_sub_dict(gt_val, res_val):
    """
    Recursively compares ground truth vs results.
    Returns (matches, total_eligible_fields).
    """
    # If ground truth is None, ignore it based on instructions
    if gt_val is None:
        return 0, 0

    # Case 1: Nested Dictionaries
    if isinstance(gt_val, dict):
        if not isinstance(res_val, dict):
            # If the result didn't even output a dict, all subfields are misses
            return 0, sum(1 for v in gt_val.values() if v is not None)
        
        matches = 0
        total = 0
        for key, value in gt_val.items():
            if value is None:
                continue
            m, t = evaluate_sub_dict(value, res_val.get(key))
            matches += m
            total += t
        return matches, total

    # Case 2: Lists of objects (e.g., rent_roll rows, demographics catchment areas, assets)
    elif isinstance(gt_val, list):
        if not isinstance(res_val, list):
            # Calculate total non-null fields inside the ground truth list elements
            total_fields = 0
            for item in gt_val:
                if isinstance(item, dict):
                    total_fields += sum(1 for v in item.values() if v is not None)
                elif item is not None:
                    total_fields += 1
            return 0, total_fields

        matches = 0
        total = 0
        # Positional alignment comparison (Index-by-index matching)
        for i, gt_item in enumerate(gt_val):
            res_item = res_val[i] if i < len(res_val) else None
            m, t = evaluate_sub_dict(gt_item, res_item)
            matches += m
            total += t
            
        # Penalty for extra hallucinated items in the LLM list
        if len(res_val) > len(gt_val):
            total += (len(res_val) - len(gt_val))
            
        return matches, total

    # Case 3: Primitive values (Strings, Numbers, Bools)
    else:
        # Strict typing conversion safety check for numerical discrepancies (e.g., 6 vs 6.0)
        if isinstance(gt_val, (int, float)) and isinstance(res_val, (int, float)):
            return (1, 1) if np.isclose(np.round(gt_val), np.round(res_val)) else (0, 1)
        
        return (1, 1) if str(gt_val).lower().strip()[:15] == str(res_val).lower().strip()[:15] else (0, 1)


def _filter_gt_res_for_schema(
    gt_sub: dict,
    res_sub: Any,
    sub_dict: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return aligned (gt, res) dicts for comparison, or None if this sub-dict should be skipped."""
    if gt_sub is None or not isinstance(gt_sub, dict):
        return None
    if not isinstance(res_sub, dict):
        res_sub = {}
    skip_keys = {"confidence_answer", "floors_count", "lease_remaining_years"}
    model_keys = schemas_dict[sub_dict].model_fields.keys()
    gt_f = {
        k: v
        for k, v in gt_sub.items()
        if k in model_keys and k not in skip_keys
    }
    res_f = {
        k: v
        for k, v in res_sub.items()
        if k in model_keys and k not in skip_keys
    }
    return gt_f, res_f


def _stats_for_one_document(
    gt_content: dict[str, Any],
    res_content: dict[str, Any] | None,
    target_sub_dicts: list[str],
) -> dict[str, dict[str, int]]:
    """Per sub-dict: matches and total eligible fields for one document."""
    res_content = res_content if isinstance(res_content, dict) else {}
    stats: dict[str, dict[str, int]] = {
        sub: {"matches": 0, "total": 0} for sub in target_sub_dicts
    }
    for sub_dict in target_sub_dicts:
        gt_sub = gt_content.get(sub_dict)
        res_sub = res_content.get(sub_dict)
        pair = _filter_gt_res_for_schema(gt_sub, res_sub, sub_dict) if isinstance(gt_sub, dict) else None
        if pair is None:
            continue
        gt_f, res_f = pair
        m, t = evaluate_sub_dict(gt_f, res_f)
        stats[sub_dict]["matches"] = m
        stats[sub_dict]["total"] = t
    return stats


def _print_overall_summary_table(
    agg: dict[str, dict[str, int]],
    target_sub_dicts: list[str],
    *,
    title: str = "OVERALL SUMMARY (all PDFs)",
) -> tuple[int, int]:
    """
    Print the aggregate SUB-DICTIONARY table (same layout as legacy global report).
    Returns (total_matches, total_eligible).
    """
    print("\n" + "=" * 50)
    print(title)
    print("=" * 50)
    print(f"{'SUB-DICTIONARY':<25} | {'ACCURACY':<10} | {'MATCHES/TOTAL'}")
    print("=" * 50)

    overall_matches = 0
    overall_total = 0

    for sub_dict in target_sub_dicts:
        m = agg[sub_dict]["matches"]
        t = agg[sub_dict]["total"]
        overall_matches += m
        overall_total += t
        accuracy = (m / t * 100) if t > 0 else 0.0
        print(f"{sub_dict:<25} | {accuracy:>8.2f}% | {m}/{t}")

    print("-" * 50)
    total_acc = (overall_matches / overall_total * 100) if overall_total > 0 else 0.0
    print(f"{'OVERALL PERFORMANCE':<25} | {total_acc:>8.2f}% | {overall_matches}/{overall_total}")
    print("=" * 50)

    return overall_matches, overall_total


def _print_document_accuracy_table(doc_label: str, stats: dict[str, dict[str, int]], sub_order: list[str]) -> tuple[int, int]:
    """
    Print SUB-DICTIONARY | ACCURACY | MATCHES/TOTAL for one PDF; return (overall_matches, overall_total).
    """
    print("\n" + "=" * 50)
    print(doc_label)
    print("=" * 50)
    print(f"{'SUB-DICTIONARY':<25} | {'ACCURACY':<10} | {'MATCHES/TOTAL'}")
    print("=" * 50)

    overall_matches = 0
    overall_total = 0

    for sub_dict in sub_order:
        m = stats[sub_dict]["matches"]
        t = stats[sub_dict]["total"]
        overall_matches += m
        overall_total += t
        accuracy = (m / t * 100) if t > 0 else 0.0
        print(f"{sub_dict:<25} | {accuracy:>8.2f}% | {m}/{t}")

    print("-" * 50)
    doc_acc = (overall_matches / overall_total * 100) if overall_total > 0 else 0.0
    print(f"{'OVERALL PERFORMANCE':<25} | {doc_acc:>8.2f}% | {overall_matches}/{overall_total}")
    print("=" * 50)

    return overall_matches, overall_total


def evaluator(ground_truth, results, target_sub_dicts):
    """
    For each PDF: print the **overall** summary table (all PDFs combined), then that
    PDF's per-section table (same column layout; last row ``OVERALL PERFORMANCE``).

    Returns weighted overall accuracy across all PDFs.
    """
    doc_rows: list[tuple[str, dict[str, dict[str, int]]]] = []
    agg: dict[str, dict[str, int]] = {sub: {"matches": 0, "total": 0} for sub in target_sub_dicts}

    for doc_id, gt_content in ground_truth.items():
        if not isinstance(gt_content, dict):
            continue
        res_content = results.get(doc_id, {})
        stats = _stats_for_one_document(gt_content, res_content, target_sub_dicts)
        doc_rows.append((str(doc_id), stats))
        for sub_dict in target_sub_dicts:
            agg[sub_dict]["matches"] += stats[sub_dict]["matches"]
            agg[sub_dict]["total"] += stats[sub_dict]["total"]

    for doc_id, stats in doc_rows:
        _print_document_accuracy_table(doc_id, stats, target_sub_dicts)

    _print_overall_summary_table(agg, target_sub_dicts, title="OVERALL SUMMARY (all PDFs)")

    grand_matches = sum(agg[s]["matches"] for s in target_sub_dicts)
    grand_total = sum(agg[s]["total"] for s in target_sub_dicts)
    weighted = (grand_matches / grand_total * 100) if grand_total > 0 else 0.0
    
    return weighted

def run_deduction(paths):

    try:
        ground_truth = {}
        keys = list(ground_truth.keys())
    except:
        ground_truth= {}
        keys = []

    for path in tqdm(paths): 
        path = Path(path)

        if path.name in keys:
            results[path.name] = ground_truth[path.name]
            continue

        full_text, _, _ = self.extract_text_stats(path)

        text_llm_by_schema = run_pdf_parse_llm_graph(self._llm, full_text)
        text_llm_by_schema = post_process_llm_values(text_llm_by_schema)

        # # save to excel 
        _ = save_parse_excel_export(
            text_llm_by_schema=text_llm_by_schema,
            source_pdf_path=path,
        )
        results[path.name] = text_llm_by_schema

    return results


def loop_post_process(results): 
    results_2 = results.copy()
    for k, v in results_2.items():
        results_2[k] = post_process_llm_values(v)
    return results_2 


if __name__ == "__main__":

    target_sub_dicts = [
        "metadata_from_text", 
        "rent_roll_report", 
        "building_report", 
        "financial_statement", 
        "demographics_report"
    ]

    self = PdfParseOrchestrator(context, config)
    self._llm = PdfParseGptBridge(context, config)
    self._llm._prompt_path = Path(r"C:\Users\de larrard alexandre\OneDrive - The Boston Consulting Group, Inc\Documents\repos_github\ordaly\api\app\src\gpt_extraction\prompt_templates")

    # run tests
    results = {}
    root = Path(r"C:\Users\de larrard alexandre\OneDrive - The Boston Consulting Group, Inc\Documents\repos_github\ordaly\data\crexi")
    paths = glob(str(root / Path("retail/*.pdf")))
    results = run_deduction(paths)

    json.dump(results, open(root / Path(f"results_1.json"), "w"))

    # evaluate retails 
    with open(root /  Path("ground_truth_all.json"), "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    evaluator(ground_truth, results, target_sub_dicts)


### TODAY

# ==================================================
# OVERALL SUMMARY (all PDFs)
# ==================================================
# SUB-DICTIONARY            | ACCURACY   | MATCHES/TOTAL
# ==================================================
# metadata_from_text        |    93.29% | 278/298
# rent_roll_report          |    43.86% | 840/1915
# building_report           |    65.55% | 196/299
# financial_statement       |    57.24% | 245/428
# demographics_report       |    64.45% | 301/467
# --------------------------------------------------
# OVERALL PERFORMANCE       |    54.59% | 1860/3407
# ==================================================

# ==================================================
# OVERALL SUMMARY (all PDFs)
# ==================================================
# SUB-DICTIONARY            | ACCURACY   | MATCHES/TOTAL
# ==================================================
# metadata_from_text        |    94.30% | 281/298
# rent_roll_report          |    44.16% | 850/1925
# building_report           |    65.55% | 196/299
# financial_statement       |    57.24% | 245/428
# demographics_report       |    64.45% | 301/467
# --------------------------------------------------
# OVERALL PERFORMANCE       |    54.81% | 1873/3417
# ==================================================