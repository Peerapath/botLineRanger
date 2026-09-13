"""
Script to extract version from main.py and update latest_version.json
"""
import re
import json
import sys
import os

def extract_version_from_main(main_file="main.py"):
    """Extract CURRENT_VERSION from main.py"""
    try:
        with open(main_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find CURRENT_VERSION = "x.x.x"
        pattern = r'CURRENT_VERSION\s*=\s*["\']([^"\']+)["\']'
        match = re.search(pattern, content)
        
        if match:
            return match.group(1)
        else:
            print(f"Warning: CURRENT_VERSION not found in {main_file}")
            return None
    except Exception as e:
        print(f"Error reading {main_file}: {e}")
        return None

def update_version_json(json_file, version):
    """Update version in latest_version.json"""
    try:
        # Read existing JSON or create new
        if os.path.exists(json_file):
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {}
        
        # Update version
        data['version'] = version
        
        # Write back
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        print(f"Successfully updated version to {version} in {json_file}")
        return True
    except Exception as e:
        print(f"Error updating {json_file}: {e}")
        return False

if __name__ == "__main__":
    main_file = "main.py"
    json_file = "default_config/latest_version.json"
    
    # Allow custom paths from command line
    if len(sys.argv) >= 2:
        main_file = sys.argv[1]
    if len(sys.argv) >= 3:
        json_file = sys.argv[2]
    
    # Extract version
    version = extract_version_from_main(main_file)
    
    if version:
        success = update_version_json(json_file, version)
        sys.exit(0 if success else 1)
    else:
        print("Failed to extract version")
        sys.exit(1)

