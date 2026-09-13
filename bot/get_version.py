"""
Simple script to extract and print version from main.py
For use with batch files
"""
import re
import sys

def get_version(main_file="main.py"):
    try:
        with open(main_file, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r'CURRENT_VERSION\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            print(match.group(1))
            return 0
    except:
        pass
    print("0.0.0")
    return 1

if __name__ == "__main__":
    main_file = sys.argv[1] if len(sys.argv) > 1 else "main.py"
    sys.exit(get_version(main_file))

