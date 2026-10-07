"""Production editorial contract, distinct from the preserved v1 pilot fixture."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import hashlib
from pathlib import Path
import re
from validate_issue import _url_key, _unique_object
from topics import validate_topic, validate_topic_evidence, validate_provenance, parse_timestamp, safe_url

CATEGORIES = {"news": ("新聞", "News"), "papers": ("論文", "Papers"),
              "products": ("新產品", "Products"), "writing": ("專家文章", "Writing"),
              "tools": ("工程工具", "Tools"), "engineering": ("工程實戰", "Practice")}
CONTRACT = json.loads((Path(__file__).resolve().parents[2]/'daily/data/contract.json').read_text(encoding='utf-8'))
LOCALES = tuple(CONTRACT['locales'])


def edition_today():
    """Publication and review dates use the newsletter's Taipei calendar."""
    return datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Taipei')).date()


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("expected YYYY-MM-DD")
    return date.fromisoformat(value)


def summary_policy_for(issue_date):
    """Use the latest policy effective on this edition, independent of list order."""
    day = valid_date(issue_date)
    eligible = [p for p in CONTRACT['summary_policies']
                if valid_date(p['effective_from']) <= day]
    return max(eligible, key=lambda p: p['effective_from']) if eligible else None


def summary_content_digest(item, issue_date):
    """Bind a human length exception to the exact bilingual text and sources."""
    values = [issue_date, item.get('id'), item.get('source_url'), item.get('summary_sources', [])]
    values.extend((item.get(locale) if isinstance(item.get(locale), dict) else {}).get(field) for locale in LOCALES
                  for field in ('title', 'summary', 'takeaway', 'caveat'))
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def valid_summary_source_url(value):
    """Use a shared raw URL grammar; do not silently repair malformed authorities."""
    try:
        if not isinstance(value, str) or len(value) > 2000 or re.search(r'[\s\ufeff]', value):
            return False
        match = re.match(r'https://([a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::443)?(?=[/?#]|$)', value, re.ASCII | re.I)
        if not match:
            return False
        host = match.group(1)
        labels = host.split('.')
        if (len(host) > 253 or not re.match(r'[a-z]', labels[-1], re.ASCII | re.I)
                or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label, re.ASCII | re.I) for label in labels)):
            return False
        value.encode('utf-8')
        safe_url(value)
        return True
    except (ValueError, TypeError, UnicodeError):
        return False


def summary_errors(item, issue_date, today=None):
    """Enforce the dated editorial policy without rewriting historical editions."""
    sources = item.get('summary_sources')
    if 'summary_sources' in item:
        try:
            if (not isinstance(sources, list) or not 1 <= len(sources) <= 8
                    or any(not valid_summary_source_url(url) for url in sources)
                    or len(set(sources)) != len(sources)):
                raise ValueError('invalid sources')
        except (ValueError, TypeError, AttributeError):
            return ['summary_sources must contain 1–8 unique safe HTTPS source URLs']
    policy = summary_policy_for(issue_date)
    if policy is None:
        return ['short summary exceptions are unavailable for this edition date'] if item.get('summary_length_exception') is not None else []
    fields = item.get(policy['locale'])
    value = fields.get('summary') if isinstance(fields, dict) else None
    if not isinstance(value, str):
        return ['Traditional Chinese summary is required']
    # Unicode White_Space, shared explicitly with the JavaScript validator.
    length = len(re.sub(r'[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]', '', value))
    exception = item.get('summary_length_exception')
    if exception is not None:
        keys = {'schema_version', 'reason', 'reviewed', 'reviewed_on', 'actual_characters', 'content_sha256'}
        valid = (isinstance(exception, dict) and set(exception) == keys
                 and type(exception.get('schema_version')) in (int, float) and exception['schema_version'] == 1
                 and exception.get('reason') in policy.get('short_summary_exceptions', [])
                 and exception.get('reviewed') is True
                 and type(exception.get('actual_characters')) in (int, float) and exception['actual_characters'] == length
                 and 0 < length < policy['min_characters'] and bool(sources))
        try:
            valid = valid and valid_date(issue_date) <= valid_date(exception['reviewed_on']) <= (today or edition_today())
        except (ValueError, TypeError, KeyError):
            valid = False
        try:
            bound = valid and exception.get('content_sha256') == summary_content_digest(item, issue_date)
        except (TypeError, ValueError, UnicodeError):
            bound = False
        if not bound:
            return ['short summary exception requires a current, content-bound source review']
        return []
    if not policy['min_characters'] <= length <= policy['max_characters']:
        return [f"Traditional Chinese summary must contain {policy['min_characters']}–{policy['max_characters']} non-whitespace characters (target {policy['target_characters']}); found {length}"]
    return []


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
        if issue_date > (today or edition_today()):
            errors.append("edition date must not be in the future")
        if valid_date(issue.get("reviewed_on")) > (today or edition_today()):
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
            url.encode('utf-8')
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
        if issue_date:
            errors.extend(f'{prefix}: {error}' for error in summary_errors(item, issue_date.isoformat(), today))
    return errors


def load_edition(path):
    issue = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    errors = validate_edition(issue)
    if errors:
        raise ValueError(f"{path}: " + "; ".join(errors))
    if Path(path).stem != issue["date"]:
        raise ValueError("edition filename must match its date")
    return issue
