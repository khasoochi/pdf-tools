"""Allow running pdfcompress as a module: python -m pdfcompress"""

from .cli import main

if __name__ == "__main__":
    main()
