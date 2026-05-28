from src.context import AppContext

class SqlHelper:

    def __init__(
        self,
        context: AppContext,
    ):
        self._context = context
        self._log = context.log

   