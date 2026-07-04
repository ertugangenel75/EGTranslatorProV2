# -*- coding: utf-8 -*-
import re, json

# URL encoding — IronPython 2.7 uyumlu
try:
    from urllib import quote
except Exception:
    from urllib.parse import quote

# .NET WebClient — IronPython 2.7'de urllib2'den cok daha kararli
try:
    import clr
    clr.AddReference('System')
    clr.AddReference('System.Net')
    import System
    from System.Net import WebClient, ServicePointManager, SecurityProtocolType
    from System.Text import Encoding
    try:
        ServicePointManager.SecurityProtocol = (
            SecurityProtocolType.Tls12 | SecurityProtocolType.Tls11
        )
    except Exception:
        pass
    try:
        ServicePointManager.ServerCertificateValidationCallback = \
            System.Net.Security.RemoteCertificateValidationCallback(
                lambda sender, cert, chain, errors: True
            )
    except Exception:
        pass
    _HAS_WEBCLIENT = True
except Exception:
    _HAS_WEBCLIENT = False

from data_loader import normalize_key

STOP_TOKENS = set(['tr', 'en', 'es', 'pt', 'ru'])


class TranslatorEngine(object):
    def __init__(self, data, use_dictionary=True, use_api=False,
                 use_cache=True, smart_split=True):
        self.data = data
        self.use_dictionary = use_dictionary
        self.use_api = use_api
        self.use_cache = use_cache
        self.smart_split = smart_split
        self.cache = {}

    def translate(self, text, src, tgt, manual=''):
        original = text or ''
        manual = (manual or '').strip()
        if manual:
            return manual, 'MANUAL'
        if not original.strip() or src == tgt:
            return original, 'UNCHANGED'
        ck = (src, tgt, normalize_key(original))
        if self.use_cache and ck in self.cache:
            return self.cache[ck], 'CACHE'

        result = None
        method = 'UNCHANGED'

        if self.use_dictionary:
            result = self.data.get_exact(src, tgt, original)
            if result:
                method = 'DICT'

        if not result and self.smart_split:
            split = self._smart_translate(original, src, tgt)
            if split and normalize_key(split) != normalize_key(original):
                result = split
                method = 'SMART'

        if not result and self.use_api:
            api_val = self._mymemory_translate(original, src, tgt)
            if api_val:
                result = api_val
                method = 'API'

        if not result:
            result = original
            method = 'UNCHANGED'

        if self.use_cache:
            self.cache[ck] = result
        return result, method

    def _smart_translate(self, text, src, tgt):
        chunks = re.split(r'([_\-\/\(\)\[\]\s\.]+)', text)
        out = []
        changed = False
        for chunk in chunks:
            if not chunk:
                continue
            if re.match(r'^[_\-\/\(\)\[\]\s\.]+$', chunk):
                out.append(chunk)
                continue
            nk = normalize_key(chunk)
            if nk in STOP_TOKENS:
                out.append(chunk)
                continue
            exact = self.data.get_exact(src, tgt, chunk)
            if exact:
                out.append(exact)
                changed = True
                continue
            token = self.data.get_token(src, tgt, chunk)
            if token:
                out.append(token)
                changed = True
                continue
            # Camel split: sayı-harf karışımlarını (3D, 2D vb.) bütün tut
            camel_parts = re.findall(
                r'\d+[A-Z]+|[A-Z]?[a-z\u00e7\u011f\u0131\u00f6\u015f\u00fc]+|[A-Z]+(?=[A-Z]|$)|\d+',
                chunk, re.UNICODE
            )
            if len(camel_parts) > 1:
                local = []
                local_changed = False
                for part in camel_parts:
                    p = self.data.get_token(src, tgt, part)
                    if p:
                        local.append(p)
                        local_changed = True
                    else:
                        local.append(part)
                out.append(u' '.join(local))
                changed = changed or local_changed
            else:
                out.append(chunk)
        return u''.join(out) if changed else None

    def _mymemory_translate(self, text, src, tgt):
        """
        MyMemory ucretsiz ceviri API'si.
        Once .NET WebClient dener — IronPython 2.7'de SSL ve encoding
        sorunlarini cozer. Basaramazsa urllib2/urllib fallback yapar.
        """
        try:
            q = quote(text.encode('utf-8')) if hasattr(text, 'encode') else quote(text)
            url = (
                'https://api.mymemory.translated.net/get?q=%s&langpair=%s|%s'
                % (q, src.lower(), tgt.lower())
            )

            raw = None

            if _HAS_WEBCLIENT:
                try:
                    wc = WebClient()
                    wc.Encoding = Encoding.UTF8
                    wc.Headers.Add('User-Agent', 'Mozilla/5.0')
                    raw = wc.DownloadString(url)
                except Exception:
                    raw = None

            if not raw:
                try:
                    try:
                        from urllib2 import urlopen, Request
                    except Exception:
                        from urllib.request import urlopen, Request
                    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    data = urlopen(req, timeout=5).read()
                    try:
                        raw = data.decode('utf-8')
                    except Exception:
                        raw = str(data)
                except Exception:
                    return None

            if not raw:
                return None

            try:
                obj = json.loads(raw)
            except Exception:
                return None

            val = (
                ((obj or {}).get('responseData') or {})
                .get('translatedText') or ''
            ).strip()

            if not val:
                return None
            if normalize_key(val) == normalize_key(text):
                return None
            lval = val.upper()
            if lval.startswith('PLEASE SELECT') or lval.startswith('MYMEMORY WARNING'):
                return None
            return val

        except Exception:
            return None
