"""
Text formatting utilities for Discord display.
"""

def to_sans_serif_bold(text: str) -> str:
    """
    Convert regular text to Unicode sans-serif bold characters.
    These characters display as bold sans-serif in Discord.
    
    Example: "Team Phoenix" -> "𝗧𝗲𝗮𝗺 𝗣𝗵𝗼𝗲𝗻𝗶𝘅"
    """
    # Unicode Mathematical Alphanumeric Symbols - Sans-serif Bold
    # Uppercase: U+1D5D4 to U+1D5ED (A-Z)
    # Lowercase: U+1D5EE to U+1D607 (a-z)
    # Digits: U+1D7EC to U+1D7F5 (0-9)
    
    result = []
    for char in text:
        if 'A' <= char <= 'Z':
            # Convert A-Z to bold sans-serif
            result.append(chr(0x1D5D4 + (ord(char) - ord('A'))))
        elif 'a' <= char <= 'z':
            # Convert a-z to bold sans-serif
            result.append(chr(0x1D5EE + (ord(char) - ord('a'))))
        elif '0' <= char <= '9':
            # Convert 0-9 to bold sans-serif
            result.append(chr(0x1D7EC + (ord(char) - ord('0'))))
        else:
            # Keep other characters as-is (spaces, hyphens, emojis, etc.)
            result.append(char)
    
    return ''.join(result)


# Test examples
if __name__ == "__main__":
    print("Testing sans-serif bold conversion:")
    print(f"Team Phoenix -> {to_sans_serif_bold('Team Phoenix')}")
    print(f"Team Dragon vs Team Phoenix -> {to_sans_serif_bold('Team Dragon vs Team Phoenix')}")
    print(f"Match 123 -> {to_sans_serif_bold('Match 123')}")
