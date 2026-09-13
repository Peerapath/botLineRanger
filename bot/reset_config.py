"""
Script to reset email in config.ini for distribution
"""
import re
import sys

def reset_email_in_config(config_file):
    """Reset email to default value"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Replace email with default value
        pattern = r'email\s*=\s*[^\s\n]+@[^\s\n]+'
        replacement = 'email = email'
        new_content = re.sub(pattern, replacement, content)

        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(new_content)

        print(f"Successfully reset email in {config_file}")
        return True
    except Exception as e:
        print(f"Error resetting email: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python reset_config.py <config_file>")
        sys.exit(1)

    config_file = sys.argv[1]
    success = reset_email_in_config(config_file)
    sys.exit(0 if success else 1)
