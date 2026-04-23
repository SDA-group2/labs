import os
import time
import smtplib
from html import escape
from typing import Any, Iterable

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient, ReturnDocument
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


load_dotenv()


MONGODB_URI = os.getenv("MONGODB_URI", "")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "worker@mzinga.io")


def get_env_or_fail(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def children_to_html(children: Iterable[Any]) -> str:
    return "".join(node_to_html(child) for child in children or [])


def text_leaf_to_html(node: dict[str, Any]) -> str:
    text = escape(str(node.get("text", "")))

    if node.get("bold"):
        text = f"<strong>{text}</strong>"
    if node.get("italic"):
        text = f"<em>{text}</em>"

    return text


def node_to_html(node: Any) -> str:
    if not isinstance(node, dict):
        return escape(str(node))

    if "text" in node:
        return text_leaf_to_html(node)

    node_type = node.get("type")
    children_html = children_to_html(node.get("children", []))

    if node_type == "paragraph":
        return f"<p>{children_html}</p>"
    if node_type == "h1":
        return f"<h1>{children_html}</h1>"
    if node_type == "h2":
        return f"<h2>{children_html}</h2>"
    if node_type == "ul":
        return f"<ul>{children_html}</ul>"
    if node_type == "li":
        return f"<li>{children_html}</li>"
    if node_type == "link":
        url = escape(str(node.get("url", "#")), quote=True)
        return f'<a href="{url}">{children_html}</a>'

    return children_html


def slate_to_html(body: Any) -> str:
    if not isinstance(body, list):
        return "<p></p>"
    return "".join(node_to_html(node) for node in body)


def normalize_relation_value(value: Any) -> ObjectId | None:
    if isinstance(value, ObjectId):
        return value

    if isinstance(value, str):
        try:
            return ObjectId(value)
        except Exception:
            return None

    if isinstance(value, dict):
        nested_id = value.get("id") or value.get("_id") or value.get("value")
        if isinstance(nested_id, ObjectId):
            return nested_id
        if isinstance(nested_id, str):
            try:
                return ObjectId(nested_id)
            except Exception:
                return None

    return None


def extract_user_ids(relations: Any) -> list[ObjectId]:
    if not isinstance(relations, list):
        return []

    user_ids: list[ObjectId] = []
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        if rel.get("relationTo") != "users":
            continue

        obj_id = normalize_relation_value(rel.get("value"))
        if obj_id is not None:
            user_ids.append(obj_id)

    return user_ids


def resolve_emails(users_collection, relations: Any) -> list[str]:
    user_ids = extract_user_ids(relations)
    if not user_ids:
        return []

    users = list(
        users_collection.find(
            {"_id": {"$in": user_ids}},
            {"email": 1},
        )
    )

    emails: list[str] = []
    for user in users:
        email = user.get("email")
        if isinstance(email, str) and email.strip():
            emails.append(email.strip())

    return emails


def send_email(subject: str, html_body: str, to_emails: list[str], cc_emails: list[str], bcc_emails: list[str]) -> None:
    if not to_emails:
        raise ValueError("No recipient emails found in 'tos'.")

    message = MIMEMultipart("alternative")
    message["From"] = EMAIL_FROM
    message["To"] = ", ".join(to_emails)
    message["Subject"] = subject

    if cc_emails:
        message["Cc"] = ", ".join(cc_emails)

    message.attach(MIMEText(html_body, "html", "utf-8"))

    all_recipients = to_emails + cc_emails + bcc_emails

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.sendmail(EMAIL_FROM, all_recipients, message.as_string())


def process_one(communications, users_collection) -> bool:
    doc = communications.find_one_and_update(
        {"status": "pending"},
        {"$set": {"status": "processing"}},
        return_document=ReturnDocument.AFTER,
    )

    if doc is None:
        return False

    doc_id = doc["_id"]
    print(f"[worker] Picked communication {doc_id}")

    try:
        subject = str(doc.get("subject", "")).strip()
        body = doc.get("body", [])
        html = slate_to_html(body)

        to_emails = resolve_emails(users_collection, doc.get("tos"))
        cc_emails = resolve_emails(users_collection, doc.get("ccs"))
        bcc_emails = resolve_emails(users_collection, doc.get("bccs"))

        send_email(subject, html, to_emails, cc_emails, bcc_emails)

        communications.update_one(
            {"_id": doc_id},
            {"$set": {"status": "sent"}},
        )
        print(f"[worker] Communication {doc_id} marked as sent")

    except Exception as exc:
        communications.update_one(
            {"_id": doc_id},
            {"$set": {"status": "failed"}},
        )
        print(f"[worker] Communication {doc_id} failed: {exc}")

    return True


def main() -> None:
    mongodb_uri = get_env_or_fail("MONGODB_URI")

    client = MongoClient(mongodb_uri)
    db = client.get_database()
    communications = db["communications"]
    users_collection = db["users"]

    print("[worker] Started")
    print(f"[worker] Poll interval: {POLL_INTERVAL_SECONDS}s")
    print(f"[worker] SMTP: {SMTP_HOST}:{SMTP_PORT}")

    while True:
        found = process_one(communications, users_collection)
        if not found:
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()