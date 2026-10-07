"""Validate local newsletter JPEGs before any generated output is written."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import warnings
from PIL import Image

MAX_IMAGE_BYTES = 300 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_SIDE = 2048
MAX_PIXELS = 4_194_304


def validate_image(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('image must be a regular local file')
    size = path.stat().st_size
    if not 0 < size <= MAX_IMAGE_BYTES:
        raise ValueError('image exceeds the 300 KiB budget')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = image.size
                if image.format != 'JPEG':
                    raise ValueError('only verified JPEG images may be published')
                if min(width, height) <= 0 or max(width, height) > MAX_SIDE or width * height > MAX_PIXELS:
                    raise ValueError('image dimensions exceed the rendering budget')
                image.verify()
            with Image.open(path) as image:
                image.load()  # Verify compressed pixels, not just the header.
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError('image cannot be safely decoded') from error
    return {'width': width, 'height': height, 'bytes': size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def load_images(root, required_items):
    root = Path(root).resolve()
    manifest_path = root/'daily/data/image-manifest.json'
    if any(p.is_symlink() for p in (manifest_path, *manifest_path.parents)) or not manifest_path.is_file() or manifest_path.stat().st_size > 4_000_000:
        raise ValueError('image manifest must be a bounded regular local file')
    from validate_issue import _unique_object
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
    if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1 or not isinstance(manifest.get('images'), list) or set(manifest) != {'schema_version', 'image_policy', 'images'}:
        raise ValueError('invalid image manifest')
    images = {}
    used_paths = set()
    total = 0
    required_ids = {item['id'] for item in required_items}
    for entry in manifest['images']:
        if not isinstance(entry, dict) or set(entry) != {'story_id', 'width', 'height', 'bytes', 'sha256', 'alt', 'caption', 'source_url', 'ai_generated', 'path', 'credit'}:
            raise ValueError('image entry has unsupported metadata')
        sid = entry.get('story_id')
        path = entry.get('path', '')
        if not isinstance(sid, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', sid) or sid in images:
            raise ValueError('invalid or duplicate image story ID')
        if not isinstance(path, str) or not re.fullmatch(r'daily/assets/stories/[a-z0-9-]+\.jpg', path) or path in used_paths:
            raise ValueError('image paths must be unique safe local JPEG paths')
        target = root/PurePosixPath(path)
        if any(p.is_symlink() for p in (target, *target.parents)) or not target.resolve().is_relative_to(root):
            raise ValueError('image symbolic links are not allowed')
        info = validate_image(target)
        if any(type(entry.get(k)) is not type(v) or entry[k] != v for k, v in info.items()):
            raise ValueError('image metadata/hash does not match bytes')
        if entry.get('ai_generated') is not True:
            raise ValueError('this image collection requires explicit AI illustration labeling')
        for field in ('alt', 'caption', 'credit'):
            if not isinstance(entry.get(field), dict) or any(not isinstance(entry[field].get(l), str) or not entry[field][l].strip() for l in ('zh-TW', 'en')):
                raise ValueError('image requires bilingual alt, caption and credit')
        from validate_issue import _url_key
        _url_key(entry.get('source_url'))
        images[sid] = entry
        used_paths.add(path)
        if sid in required_ids:
            total += info['bytes']
    if total > MAX_TOTAL_BYTES:
        raise ValueError('edition image collection exceeds the 2 MiB budget')
    for item in required_items:
        if item['id'] not in images:
            raise ValueError('enhanced story requires a verified image: '+item['id'])
        if images[item['id']]['source_url'] != item['source_url']:
            raise ValueError('image provenance does not match story source')
    return images
