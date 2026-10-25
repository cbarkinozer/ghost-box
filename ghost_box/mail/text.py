"""Decode MIME using the standard library; never render remote email HTML."""

import base64
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        if tag in {"br", "p", "div", "tr", "li"}:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def decode_message(data):
    raw = data["raw"]
    message = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    )
    part = message.get_body(preferencelist=("plain", "html"))
    body = part.get_content(errors="replace") if part else ""
    if part and part.get_content_type() == "text/html":
        parser = PlainHTML()
        parser.feed(body)
        body = "".join(parser.text).strip()
    return {
        "id": data["id"], "thread_id": data["threadId"],
        "timestamp": int(data["internalDate"]),
        "sender": str(message.get("From", "")),
        "recipients": str(message.get("To", "")),
        "cc": str(message.get("Cc", "")),
        "reply_to": str(message.get("Reply-To", "")),
        "message_id": str(message.get("Message-ID", "")),
        "references": str(message.get("References", "")),
        "attachment_count": sum(1 for item in message.walk()
                                if item.get_content_disposition() == 'attachment'
                                or (item.get_filename() and item.get_content_disposition() != 'inline')),
        "subject": str(message.get("Subject", "(no subject)")), "body": body,
    }
