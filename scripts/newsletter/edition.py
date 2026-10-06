"""Production editorial contract, distinct from the preserved v1 pilot fixture."""
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
from validate_issue import _url_key, _unique_object
from topics import validate_topic, validate_topic_evidence, validate_provenance, parse_timestamp, safe_url

CATEGORIES = {"news": ("新聞", "News"), "papers": ("論文", "Papers"),
              "products": ("新產品", "Products"), "writing": ("專家文章", "Writing"),
              "tools": ("工程工具", "Tools"), "engineering": ("工程實戰", "Practice")}
CONTRACT = json.loads((Path(__file__).resolve().parents[2]/'daily/data/contract.json').read_text(encoding='utf-8'))
LOCALES = tuple(CONTRACT['locales'])


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("expected YYYY-MM-DD")
    return date.fromisoformat(value)


def validate_edition(issue, today=None):
    """Fail closed on unreviewed, synthetic, incomplete, unsafe or future content."""
    errors = []
    if not isinstance(issue, dict):
        return ["edition must be an object"]
    if type(issue.get("schema_version")) is not int or issue.get("schema_version") != 2:
        errors.append("schema_version must be integer 2")
    if issue.get("synthetic") is not False or issue.get("reviewed") is not True:
        errors.append("only non-synthetic, editorially reviewed editions may be published")
    try:
        issue_date = valid_date(issue.get("date"))
        if issue_date > (today or date.today()):
            errors.append("edition date must not be in the future")
        if valid_date(issue.get("reviewed_on")) > (today or date.today()):
            errors.append("review date must not be in the future")
    except ValueError:
        issue_date = None
        errors.append("date and reviewed_on must be real ISO calendar dates")
    for field in CONTRACT['issue_text_fields']:
        for locale in LOCALES:
            value = issue.get(field, {})
            if not isinstance(value, dict) or not isinstance(value.get(locale), str) or not value[locale].strip():
                errors.append(f"{field}.{locale} is required")
    topic = None
    if 'topic' in issue:
        try:
            topic = validate_topic(issue['topic'])
        except (ValueError, TypeError) as error:
            errors.append('topic: '+str(error))
    if topic and topic['keywords']:
        discovery = issue.get('discovery')
        if not isinstance(discovery, dict):
            errors.append('topic editions require discovery metadata')
        else:
            status = discovery.get('search_status')
            if status not in ('completed','partial'):
                errors.append('topic edition requires a successful keyword discovery search')
            if status == 'completed' and (discovery.get('failures') or discovery.get('coverage_warnings') or any(isinstance(q,dict) and q.get('status')!='ok' for q in (discovery.get('searches') if isinstance(discovery.get('searches'),list) else []))):
                errors.append('completed discovery cannot conceal failures or coverage warnings')
            for receipt in discovery.get('searches',[]) if isinstance(discovery.get('searches'),list) else []:
                try:
                    validate_provenance(receipt)
                except (ValueError, TypeError, UnicodeError):
                    errors.append('discovery search receipt is malformed')
            if status == 'partial' and discovery.get('limitations_acknowledged') is not True:
                errors.append('editor must acknowledge partial-search limitations before publication')
            if not isinstance(discovery.get('searches'), list) or not any(isinstance(q,dict) and q.get('status')=='ok' and q.get('provider') in ('gdelt','arxiv') for q in discovery.get('searches',[])):
                errors.append('topic edition requires a successful search receipt')
            try:
                collected = parse_timestamp(discovery.get('collected_at'))
                if not collected.tzinfo or issue_date and collected.date() > issue_date:
                    errors.append('discovery collection timestamp must be timezone-aware and no later than edition date')
            except (ValueError, TypeError, AttributeError):
                errors.append('discovery.collected_at must be an ISO timestamp')
    items = issue.get("items")
    if not isinstance(items, list):
        return errors + ["items must be an array"]
    if not CONTRACT['min_items'] <= len(items) <= CONTRACT['max_items']:
        errors.append("publish 6–14 verified picks; target about 10, never pad with invented stories")
    ids, urls = set(), set()
    for i, item in enumerate(items):
        prefix = f"items[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        slug = item.get("id")
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slug) or slug in ids:
            errors.append(f"{prefix}.id must be a unique safe slug")
        ids.add(str(slug))
        if item.get("category") not in CATEGORIES:
            errors.append(f"{prefix}.category is invalid")
        if not isinstance(item.get("source"), str) or not item["source"].strip():
            errors.append(f"{prefix}.source is required")
        try:
            url = safe_url(item.get("source_url"))
            if url in urls:
                errors.append(f"{prefix}.source_url is duplicated")
            urls.add(url)
        except (ValueError, UnicodeError):
            errors.append(f"{prefix}.source_url must be safe HTTPS")
        try:
            published = valid_date(item.get("published_date"))
            if issue_date and published > issue_date:
                errors.append(f"{prefix}.published_date is later than the edition")
        except ValueError:
            errors.append(f"{prefix}.published_date must be a real date")
        if topic and topic['keywords']:
            errors.extend(f'{prefix}: {e}' for e in validate_topic_evidence(item, topic))
            if item.get('date_verification_required') is True:
                errors.append(f'{prefix}: source publication date still needs verification')
            try:
                if issue_date and valid_date(item.get('published_date')) < issue_date-timedelta(days=topic['lookback_days']):
                    errors.append(f'{prefix}: publication date is outside the topic lookback window')
            except ValueError:
                pass
        for locale in LOCALES:
            fields = item.get(locale, {})
            for field, maximum in CONTRACT['item_text_limits'].items():
                value = fields.get(field) if isinstance(fields, dict) else None
                if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                    errors.append(f"{prefix}.{locale}.{field} is missing or too long")
    return errors


def load_edition(path):
    issue = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    errors = validate_edition(issue)
    if errors:
        raise ValueError(f"{path}: " + "; ".join(errors))
    if Path(path).stem != issue["date"]:
        raise ValueError("edition filename must match its date")
    return issue
