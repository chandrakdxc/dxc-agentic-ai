import re


def triage(ticket):
    title = ticket.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")

    description = ticket.get("description")
    if description is None:
        description = ""

    affected_users = ticket.get("affected_users", 1)
    if not isinstance(affected_users, int) or affected_users < 1:
        raise ValueError("affected_users must be a positive int")

    text = f"{title} {description}".lower()

    if affected_users >= 50 or re.search(r"\boutage\b|\bdown\b", text):
        priority = "P1"
    elif affected_users >= 10 or re.search(r"\burgent\b|\bblocked\b", text):
        priority = "P2"
    elif affected_users >= 2:
        priority = "P3"
    else:
        priority = "P4"

    if re.search(r"\bvpn\b|\bwifi\b|\bnetwork\b", text):
        queue = "Network"
    elif re.search(r"\bpassword\b|\blogin\b|\blocked\b", text):
        queue = "Access"
    elif re.search(r"\blaptop\b|\bkeyboard\b|\bscreen\b", text):
        queue = "Hardware"
    else:
        queue = "General"

    sla_hours = {"P1": 4, "P2": 8, "P3": 24, "P4": 72}[priority]

    return {"priority": priority, "queue": queue, "sla_hours": sla_hours}