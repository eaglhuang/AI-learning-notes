"""Validate local newsletter images and declared provenance before writing outputs."""
import hashlib
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
import warnings
from PIL import Image

MAX_IMAGE_BYTES = 300 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_SIDE = 2048
MAX_PIXELS = 4_194_304
FORMATS = {'.jpg':'JPEG', '.webp':'WEBP'}


def webp_preflight(raw):
    """Read the small simple-WebP headers before Pillow/libwebp allocates a canvas.

    Only one static VP8/VP8L chunk is supported. Extended VP8X containers,
    animation and metadata chunks are intentionally outside this narrow contract.
    Specs: developers.google.com/speed/webp/docs/riff_container and RFC6386 section9.
    """
    if (len(raw)<20 or raw[:4]!=b'RIFF' or raw[8:12]!=b'WEBP'
            or int.from_bytes(raw[4:8],'little')+8!=len(raw)):
        raise ValueError('invalid bounded WebP container')
    kind=raw[12:16];size=int.from_bytes(raw[16:20],'little')
    if 20+size+(size%2)!=len(raw) or size%2 and raw[-1]!=0:
        raise ValueError('WebP must contain exactly one bounded static image chunk')
    header=raw[20:]
    if kind==b'VP8 ':
        if size<10 or header[0]&1 or header[3:6]!=b'\x9d\x01\x2a':
            raise ValueError('invalid static VP8 frame header')
        width=int.from_bytes(header[6:8],'little')&0x3fff
        height=int.from_bytes(header[8:10],'little')&0x3fff
    elif kind==b'VP8L':
        if size<5 or header[0]!=0x2f:
            raise ValueError('invalid static VP8L frame header')
        dimensions=int.from_bytes(header[1:5],'little')
        if dimensions>>29:
            raise ValueError('unsupported VP8L version')
        width=(dimensions&0x3fff)+1;height=((dimensions>>14)&0x3fff)+1
    else:
        raise ValueError('only simple static VP8/VP8L WebP containers are supported')
    if min(width,height)<=0 or max(width,height)>MAX_SIDE or width*height>MAX_PIXELS:
        raise ValueError('WebP dimensions exceed the rendering budget before decoding')
    return width,height


def validate_image(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('image must be a regular local file')
    size = path.stat().st_size
    if not 0 < size <= MAX_IMAGE_BYTES:
        raise ValueError('image exceeds the 300 KiB budget')
    with path.open('rb') as handle:
        raw=handle.read(MAX_IMAGE_BYTES+1)
    if len(raw)!=size:
        raise ValueError('image changed or exceeded its byte budget during reading')
    # Detect WebP by bytes even with a spoofed .jpg extension. Never hand an
    # unchecked RIFF canvas to Pillow's eagerly allocated WebP decoder.
    webp_size=webp_preflight(raw) if path.suffix=='.webp' or raw[:4]==b'RIFF' else None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
                if image.format != FORMATS.get(path.suffix) or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('only static JPEG or WebP images with matching extensions may be published')
                if min(width, height) <= 0 or max(width, height) > MAX_SIDE or width * height > MAX_PIXELS:
                    raise ValueError('image dimensions exceed the rendering budget')
                if webp_size is not None and (width,height)!=webp_size:
                    raise ValueError('decoded dimensions contradict WebP preflight')
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                image.load()  # Verify compressed pixels, not just the header.
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError('image cannot be safely decoded') from error
    return {'width': width, 'height': height, 'bytes': size, 'sha256': hashlib.sha256(raw).hexdigest()}


def validate_license(root, value):
    keys={'spdx','source_url','image_url','image_git_blob_sha','license_path','license_sha256','notice_path','notice_sha256'}
    if not isinstance(value, dict) or set(value)!=keys or value.get('spdx')!='Apache-2.0':
        raise ValueError('source image requires the supported explicit license provenance')
    from topics import safe_url
    for key in ('source_url','image_url'): safe_url(value[key])
    if not isinstance(value['image_git_blob_sha'], str) or not re.fullmatch(r'[a-f0-9]{40}',value['image_git_blob_sha']):
        raise ValueError('source image requires its verified original Git blob identity')
    for kind in ('license','notice'):
        name=value[kind+'_path']; expected=value[kind+'_sha256']
        if (not isinstance(name,str) or not re.fullmatch(r'daily/assets/licenses/[A-Za-z0-9][A-Za-z0-9._-]{0,90}\.txt',name)
                or not isinstance(expected,str) or not re.fullmatch(r'[a-f0-9]{64}',expected)):
            raise ValueError('license and modification notice require safe local paths and hashes')
        path=root/PurePosixPath(name)
        if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file() or not 0<path.stat().st_size<=131072:
            raise ValueError('license and notice must be bounded regular local files')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:
            raise ValueError('license or notice hash does not match bytes')
        try: raw.decode('utf-8')
        except UnicodeError as error: raise ValueError('license or notice must be UTF-8 text') from error


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
        base_fields={'story_id', 'width', 'height', 'bytes', 'sha256', 'alt', 'caption', 'source_url', 'ai_generated', 'path', 'credit'}
        if not isinstance(entry, dict) or type(entry.get('ai_generated')) is not bool or set(entry) != base_fields | ({'license'} if entry.get('ai_generated') is False else set()):
            raise ValueError('image entry has unsupported metadata')
        sid = entry.get('story_id')
        path = entry.get('path', '')
        if not isinstance(sid, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', sid) or sid in images:
            raise ValueError('invalid or duplicate image story ID')
        if not isinstance(path, str) or not re.fullmatch(r'daily/assets/stories/[a-z0-9-]+\.(?:jpg|webp)', path) or path in used_paths:
            raise ValueError('image paths must be unique safe local JPEG or WebP paths')
        target = root/PurePosixPath(path)
        if any(p.is_symlink() for p in (target, *target.parents)) or not target.resolve().is_relative_to(root):
            raise ValueError('image symbolic links are not allowed')
        info = validate_image(target)
        if any(type(entry.get(k)) is not type(v) or entry[k] != v for k, v in info.items()):
            raise ValueError('image metadata/hash does not match bytes')
        if entry['ai_generated'] is False:
            validate_license(root,entry['license'])
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
