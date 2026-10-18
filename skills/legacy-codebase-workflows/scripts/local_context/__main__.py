"""Allow python -m local_context when scripts/ is on the module path."""
from .cli import main

raise SystemExit(main())
