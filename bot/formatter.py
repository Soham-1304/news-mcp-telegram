import re
import html
from typing import List


def sanitize_telegram_html(raw_html: str) -> str:
    """
    Escapes standalone '&', '<', and '>' that would otherwise break Telegram's HTML parser,
    while carefully keeping valid Telegram HTML tags (<b>, <i>, <u>, <s>, <a>, <code>, <pre>) intact.
    """
    tag_pattern = re.compile(r'(</?(?:b|i|u|s|code|pre)>|<a\s+href="[^"]+">|</a>)', re.IGNORECASE)
    parts = tag_pattern.split(raw_html)

    sanitized = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            # Valid allowed HTML tag
            sanitized.append(part)
        else:
            # Prose text: escape unescaped &, <, >
            text = part
            text = re.sub(r'&(?!(?:amp|lt|gt|quot);)', '&amp;', text)
            text = text.replace('<', '&lt;').replace('>', '&gt;')
            sanitized.append(text)

    return ''.join(sanitized)


def html_to_plain_text_with_links(text: str) -> str:
    """
    Converts HTML into readable plain text, preserving hyperlinks as:
    'Headline (https://...)' so links are NEVER lost even on fallback!
    """
    # Replace <a href="URL">Anchor</a> with 'Anchor (URL)'
    converted = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', r'\2 (\1)', text, flags=re.DOTALL)
    # Strip remaining HTML tags
    cleaned = re.sub(r'<[^>]+>', '', converted)
    # Unescape HTML entities
    return html.unescape(cleaned).strip()


def clean_and_format_for_telegram(text: str) -> str:
    """
    Transforms LLM output (markdown, headers, html tags) into clean,
    beautiful Telegram-compatible HTML.
    Eliminates raw artifacts like ###, <li>, <ul>, unescaped brackets.
    """
    if not text:
        return ""

    lines = text.split("\n")
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()

        # 1. Convert Markdown headers (### Header, ## Header, # Header) to bold
        header_match = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if header_match:
            header_text = header_match.group(1).strip()
            # Clean any internal markdown in the header
            header_text = re.sub(r"\*\*([^*]+)\*\*", r"\1", header_text)
            header_text = re.sub(r"\*([^*]+)\*", r"\1", header_text)
            cleaned_lines.append(f"\n<b>{header_text}</b>")
            continue

        # 2. Convert html list items <li> and </li> to bullet points
        line = re.sub(r"<\s*li\s*>", "• ", line, flags=re.IGNORECASE)
        line = re.sub(r"<\s*/\s*li\s*>", "", line, flags=re.IGNORECASE)
        line = re.sub(r"<\s*/?\s*ul\s*>", "", line, flags=re.IGNORECASE)
        line = re.sub(r"<\s*/?\s*ol\s*>", "", line, flags=re.IGNORECASE)
        line = re.sub(r"<\s*/?\s*p\s*>", "\n", line, flags=re.IGNORECASE)

        # 3. Convert markdown bullet dashes/asterisks (* item, - item) to clean unicode bullets
        bullet_match = re.match(r"^\s*[\*\-]\s+(.+)$", line)
        if bullet_match:
            line = f"• {bullet_match.group(1)}"

        # 4. Convert markdown bold **text** to <b>text</b>
        line = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", line)

        # 5. Convert markdown italic _text_ or *text* to <i>text</i>
        line = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<i>\1</i>", line)

        # 6. Convert markdown links [Anchor](http://...) to <a href="...">Anchor</a>
        line = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', line)

        # 7. Clean up markdown horizontal dividers (---, ___)
        if re.match(r"^[-*_]{3,}$", stripped):
            cleaned_lines.append("───────────────────────")
            continue

        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines)

    # Condense excess blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)

    # Sanitize entities so Telegram HTML engine never throws 400 Bad Request
    return sanitize_telegram_html(result.strip())


def chunk_message(text: str, max_chars: int = 3900) -> List[str]:
    """Splits text into chunks preserving line breaks for Telegram's 4096 character limit."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    lines = text.split("\n")
    curr = ""
    for line in lines:
        if len(curr) + len(line) + 1 > max_chars:
            chunks.append(curr.strip())
            curr = line + "\n"
        else:
            curr += line + "\n"

    if curr.strip():
        chunks.append(curr.strip())
    return chunks

