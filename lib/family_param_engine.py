# -*- coding: utf-8 -*-
"""
family_param_engine.py  —  EG Translator v2.6
==============================================
Değişiklikler v2.5 → v2.6:
  - _is_builtin_param()              : BuiltInParameter tespiti (Id < 0)
  - _storage_to_param_type()         : StorageType → ParameterType (Revit <2025)
                                       StorageType → ForgeTypeId/SpecTypeId (Revit 2025+)
  - _add_parameter_compat()          : Revit versiyonuna göre doğru AddParameter overload
  - _copy_param_value()              : Type bazlı değer kopyası (String/Integer/Double)
  - _reload_family()                 : Ortak SaveAs+LoadFamily yardımcısı
  - apply_create_and_map_in_family() : YENİ — Shared/Built-in için TR param yarat+değer kopyala
  - apply_project_family_params()    : Shared/Built-in satırlar açık hata verir,
                                       Create+Map'e yönlendirir (sessizce atlamaz)
"""
from __future__ import print_function
import os
import re
import tempfile

from Autodesk.Revit.DB import Transaction, SaveAsOptions, StorageType

# BuiltInParameterGroup — Revit versiyonuna göre import yöntemi farklı
try:
    from Autodesk.Revit.DB import BuiltInParameterGroup
    _HAS_BPG = True
except ImportError:
    try:
        import Autodesk.Revit.DB as _rdb
        BuiltInParameterGroup = _rdb.BuiltInParameterGroup
        _HAS_BPG = True
    except Exception:
        BuiltInParameterGroup = None
        _HAS_BPG = False

# ParameterType — Revit 2025'te deprecated, ama IronPython için hâlâ import edilebilir
try:
    from Autodesk.Revit.DB import ParameterType
    _HAS_PARAMETER_TYPE = True
except Exception:
    _HAS_PARAMETER_TYPE = False

# ForgeTypeId / SpecTypeId — Revit 2021+ (2025'te zorunlu)
try:
    from Autodesk.Revit.DB import ForgeTypeId
    _HAS_FORGE_TYPE = True
except Exception:
    _HAS_FORGE_TYPE = False

# ─── Revit versiyon tespiti ───────────────────────────────────────────────────
# engine fonksiyonlarına fdoc üzerinden __revit__ erişimi yoktur,
# bu yüzden versiyon numarasını fdoc.Application üzerinden okuruz.

def _revit_version_int(fdoc):
    """fdoc.Application.VersionNumber → int. Hata durumunda 2024."""
    try:
        return int(fdoc.Application.VersionNumber)
    except Exception:
        return 2024


# ─── IFamilyLoadOptions ───────────────────────────────────────────────────────
try:
    from Autodesk.Revit.DB import IFamilyLoadOptions

    class _LoadOpts(IFamilyLoadOptions):
        def OnFamilyFound(self, familyInUse, overwriteParameterValues):
            overwriteParameterValues.Value = True
            return True
        def OnSharedFamilyFound(self, sharedFamily, familyInUse,
                                source, overwriteParameterValues):
            overwriteParameterValues.Value = True
            return True
except Exception:
    class _LoadOpts(object):
        def OnFamilyFound(self, a, b):
            b.Value = True
            return True
        def OnSharedFamilyFound(self, a, b, c, d):
            d.Value = True
            return True


# ─── Yardımcılar ─────────────────────────────────────────────────────────────

def _norm(s):
    try:
        return (s or u'').strip().lower()
    except Exception:
        return u''

def _safe_str(v):
    try:
        return unicode(v)
    except Exception:
        try:
            return str(v)
        except Exception:
            return u''

def _safe_name(fn):
    return re.sub(r'[^\w]', '_', fn)[:40]

def _is_builtin_param(fp):
    """Revit built-in parametresi mi? ElementId negatifse evet."""
    try:
        return fp.Id.IntegerValue < 0
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import InternalDefinition
        return isinstance(fp.Definition, InternalDefinition)
    except Exception:
        return False


# ─── ParameterType / ForgeTypeId çözümleme ───────────────────────────────────

# Revit < 2025: ParameterType enum kullanılır
_STORAGE_TO_PARAM_TYPE = None
if _HAS_PARAMETER_TYPE:
    try:
        _STORAGE_TO_PARAM_TYPE = {
            StorageType.String:    ParameterType.Text,
            StorageType.Integer:   ParameterType.Integer,
            StorageType.Double:    ParameterType.Number,
            StorageType.ElementId: ParameterType.FamilyType,
        }
    except Exception:
        _STORAGE_TO_PARAM_TYPE = None

# Revit 2025+: ForgeTypeId / SpecTypeId kullanılır
# SpecTypeId.String.Text, SpecTypeId.Int.Integer vb.
_STORAGE_TO_FORGE = None
if _HAS_FORGE_TYPE:
    try:
        from Autodesk.Revit.DB import SpecTypeId
        _STORAGE_TO_FORGE = {
            StorageType.String:    SpecTypeId.String.Text,
            StorageType.Integer:   SpecTypeId.Int.Integer,
            StorageType.Double:    SpecTypeId.Number,
            StorageType.ElementId: None,  # FamilyType — özel işlem gerekir
        }
    except Exception:
        _STORAGE_TO_FORGE = None


def _add_parameter_compat(fmgr, name, bpg, storage_type, is_type, revit_ver):
    """
    Revit versiyonuna göre doğru AddParameter overload'ı çağırır.

    Revit < 2025  : fmgr.AddParameter(name, bpg, ParameterType, isInstance)
    Revit >= 2025 : fmgr.AddParameter(name, bpg, ForgeTypeId, isInstance)

    Döndürür: (FamilyParameter | None, error_str | None)
    """
    # is_type → isInstance = not is_type
    is_instance = not is_type

    # bpg None gelirse (BuiltInParameterGroup import başarısız) GroupTypeId dene
    if bpg is None:
        try:
            from Autodesk.Revit.DB import GroupTypeId
            bpg = GroupTypeId.General
        except Exception:
            return None, u'BuiltInParameterGroup ve GroupTypeId kullanılamıyor'

    # ── Revit 2025+ yolu ────────────────────────────────────────────────────
    if revit_ver >= 2025 and _STORAGE_TO_FORGE is not None:
        forge_id = _STORAGE_TO_FORGE.get(storage_type)
        if forge_id is None:
            # ElementId / FamilyType — yaratılamaz, atla
            return None, (
                u'StorageType.ElementId için ForgeTypeId desteklenmiyor — atlandı'
            )
        try:
            fp = fmgr.AddParameter(name, bpg, forge_id, is_instance)
            return fp, None
        except Exception as ex:
            return None, u'AddParameter(ForgeTypeId): %s' % _safe_str(ex)

    # ── Revit < 2025 yolu ───────────────────────────────────────────────────
    if _STORAGE_TO_PARAM_TYPE is not None:
        param_type = _STORAGE_TO_PARAM_TYPE.get(storage_type)
        if param_type is None:
            return None, u'Bilinmeyen StorageType — atlandı'
        try:
            fp = fmgr.AddParameter(name, bpg, param_type, is_instance)
            return fp, None
        except Exception as ex:
            return None, u'AddParameter(ParameterType): %s' % _safe_str(ex)

    # ── Hiçbiri mevcut değilse fallback: Text olarak dene ───────────────────
    try:
        if _HAS_FORGE_TYPE and _STORAGE_TO_FORGE is not None:
            from Autodesk.Revit.DB import SpecTypeId
            fp = fmgr.AddParameter(name, bpg, SpecTypeId.String.Text, is_instance)
        elif _HAS_PARAMETER_TYPE:
            fp = fmgr.AddParameter(name, bpg, ParameterType.Text, is_instance)
        else:
            return None, u'AddParameter: ne ParameterType ne ForgeTypeId mevcut'
        return fp, None
    except Exception as ex:
        return None, u'AddParameter fallback: %s' % _safe_str(ex)


def _resolve_group(group_str):
    if not _HAS_BPG or BuiltInParameterGroup is None:
        return None
    _MAP = {
        'identity data':   BuiltInParameterGroup.PG_IDENTITY_DATA,
        'dimensions':      BuiltInParameterGroup.PG_GEOMETRY,
        'ifc parameters':  BuiltInParameterGroup.PG_IFC,
        'structural':      BuiltInParameterGroup.PG_STRUCTURAL,
        'construction':    BuiltInParameterGroup.PG_CONSTRUCTION,
        'mechanical':      BuiltInParameterGroup.PG_MECHANICAL,
        'electrical':      BuiltInParameterGroup.PG_ELECTRICAL,
        'energy analysis': BuiltInParameterGroup.PG_ENERGY_ANALYSIS,
        'general':         BuiltInParameterGroup.PG_GENERAL,
        'other':           BuiltInParameterGroup.PG_GENERAL,
    }
    return _MAP.get(_norm(group_str), BuiltInParameterGroup.PG_GENERAL)


# ─── Değer kopyalama ─────────────────────────────────────────────────────────

def _copy_param_value(src_fp, tgt_fp, fdoc):
    """
    Her family type için src_fp → tgt_fp değer kopyası.
    Sadece String / Integer / Double desteklenir.
    Döndürür: (copied_count, error_str | None)
    """
    try:
        fmgr = fdoc.FamilyManager
        st = src_fp.StorageType
        copied = 0
        for ftype in fmgr.Types:
            try:
                fmgr.CurrentType = ftype
                if st == StorageType.String:
                    val = ftype.AsString(src_fp)
                    if val is not None:
                        fmgr.Set(tgt_fp, val)
                        copied += 1
                elif st == StorageType.Integer:
                    val = ftype.AsInteger(src_fp)
                    if val is not None:
                        fmgr.Set(tgt_fp, int(val))
                        copied += 1
                elif st == StorageType.Double:
                    val = ftype.AsDouble(src_fp)
                    if val is not None:
                        fmgr.Set(tgt_fp, float(val))
                        copied += 1
            except Exception:
                pass
        return copied, None
    except Exception as ex:
        return 0, _safe_str(ex)


# ─── SaveAs + LoadFamily ─────────────────────────────────────────────────────

def _reload_family(doc, fdoc, fname, save_folder=None):
    """fdoc → tmp.rfa → kapat → LoadFamily. Döndürür: (ok, err|None)"""
    folder = (save_folder or '').strip()
    if not folder or not os.path.isdir(folder):
        folder = tempfile.gettempdir()
    tmp = os.path.join(folder, _safe_name(fname) + '_egtr_v26.rfa')
    try:
        so = SaveAsOptions()
        so.OverwriteExistingFile = True
        fdoc.SaveAs(tmp, so)
    except Exception as ex:
        return False, u'SaveAs hatası: %s' % _safe_str(ex)
    finally:
        try:
            fdoc.Close(False)
        except Exception:
            pass
    if not os.path.exists(tmp):
        return False, u'Geçici dosya oluşturulamadı'
    try:
        t = Transaction(doc, u'EGCeviri — %s Yükle' % fname)
        t.Start()
        doc.LoadFamily(tmp, _LoadOpts())
        t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        return False, u'LoadFamily hatası: %s' % _safe_str(ex)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
    return True, None


# ─────────────────────────────────────────────────────────────────────────────
# A) FamilyDocument — direkt rename (Family Editor açıkken)
# ─────────────────────────────────────────────────────────────────────────────

def apply_family_doc_params(fdoc, param_rows):
    """
    Family Editor içinde açık fdoc için custom param rename.
    Shared/Built-in param'lar atlanır.
    Döndürür: (renamed_count, error_list)
    """
    renamed = 0
    errors = []
    if not fdoc or not getattr(fdoc, 'IsFamilyDocument', False):
        return renamed, [u'Verilen döküman bir Family Document değil.']
    fmgr = fdoc.FamilyManager
    tx = Transaction(fdoc, u'EGCeviri — Family Param Rename')
    tx.Start()
    try:
        for row in param_rows:
            fp = row.data.get('target_ref')
            final = (_safe_str(row.Manual) or _safe_str(row.Final) or u'').strip()
            current = _safe_str(row.Current)
            if not final or _norm(final) == _norm(current):
                continue
            if fp is None:
                errors.append(u'%s | target_ref yok' % current)
                continue
            try:
                if getattr(fp, 'IsShared', False) or _is_builtin_param(fp):
                    errors.append(
                        u'%s | Shared/Built-in — Create+Map gerekli' % current
                    )
                    continue
            except Exception:
                pass
            try:
                fmgr.RenameParameter(fp, final)
                renamed += 1
            except Exception as ex:
                err_msg = _safe_str(ex)
                if 'built-in' in err_msg.lower() or 'cannot rename' in err_msg.lower():
                    errors.append(u'%s | Built-in param — Create+Map gerekli' % current)
                else:
                    errors.append(u'%s → %s | %s' % (current, final, err_msg))
        tx.Commit()
    except Exception as ex:
        try:
            tx.RollBack()
        except Exception:
            pass
        errors.append(u'Transaction hatası: %s' % _safe_str(ex))
    return renamed, errors


# ─────────────────────────────────────────────────────────────────────────────
# B) Proje modu — Rename: EditFamily → rename → SaveAs → LoadFamily
# ─────────────────────────────────────────────────────────────────────────────

def apply_project_family_params(doc, param_rows, save_folder=None,
                                name_prefix=None, name_suffix=None):
    """
    Proje ailelerindeki custom param'ları rename eder.
    Shared/Built-in satırlar açık hata verir (Create+Map'e yönlendirilir).
    Döndürür: (total_renamed, error_list)
    """
    total_renamed = 0
    errors = []
    family_map = {}
    for row in param_rows:
        fname = row.data.get('source_family_name', u'')
        if not fname:
            errors.append(u'%s | source_family_name eksik' % row.Current)
            continue
        family_map.setdefault(fname, []).append(row)
    if not family_map:
        return total_renamed, errors

    from Autodesk.Revit.DB import FilteredElementCollector, Family
    all_families = {}
    for fam in FilteredElementCollector(doc).OfClass(Family).ToElements():
        try:
            all_families[fam.Name] = fam
        except Exception:
            pass

    for fname, rows in family_map.items():
        fam = all_families.get(fname)
        if fam is None:
            errors.append(u'%s | Projede aile bulunamadı' % fname)
            continue
        if not getattr(fam, 'IsEditable', False):
            errors.append(u'%s | IsEditable=False' % fname)
            continue
        fdoc = None
        try:
            fdoc = doc.EditFamily(fam)
        except Exception as ex:
            errors.append(u'%s | EditFamily: %s' % (fname, _safe_str(ex)))
            continue

        try:
            fmgr = fdoc.FamilyManager
            param_by_name = {}
            for fp in fmgr.Parameters:
                try:
                    param_by_name[_norm(fp.Definition.Name)] = fp
                except Exception:
                    pass
        except Exception as ex:
            errors.append(u'%s | FamilyManager: %s' % (fname, _safe_str(ex)))
            try:
                fdoc.Close(False)
            except Exception:
                pass
            continue

        tx = Transaction(fdoc, u'EGCeviri — %s Rename' % fname)
        tx.Start()
        renamed_count = 0
        tx_errors = []
        try:
            for row in rows:
                final = (_safe_str(row.Manual) or _safe_str(row.Final) or u'').strip()
                current = _safe_str(row.Current)
                if not final or _norm(final) == _norm(current):
                    continue
                fp = param_by_name.get(_norm(current))
                if fp is None:
                    tx_errors.append(u'%s | fdoc içinde bulunamadı' % current)
                    continue
                is_shared = False
                is_builtin = False
                try:
                    is_shared = bool(getattr(fp, 'IsShared', False))
                except Exception:
                    pass

                if is_shared:
                    tx_errors.append(
                        u'%s | Shared param — Create+Map gerekli (rename atlandı)' % current
                    )
                    continue

                # Built-in kontrolü: önce rename dene, exception gelirse built-in say
                try:
                    fmgr.RenameParameter(fp, final)
                    renamed_count += 1
                except Exception as ex:
                    err_msg = _safe_str(ex)
                    if 'built-in' in err_msg.lower() or 'cannot rename' in err_msg.lower() or _is_builtin_param(fp):
                        tx_errors.append(
                            u'%s | Built-in param — Create+Map gerekli (rename atlandı)' % current
                        )
                    else:
                        tx_errors.append(u'%s → %s | %s' % (current, final, err_msg))
            tx.Commit()
        except Exception as ex:
            try:
                tx.RollBack()
            except Exception:
                pass
            tx_errors.append(u'%s | Rollback: %s' % (fname, _safe_str(ex)))
            renamed_count = 0

        errors.extend(tx_errors)
        if renamed_count == 0:
            try:
                fdoc.Close(False)
            except Exception:
                pass
            continue

        ok, err = _reload_family(doc, fdoc, fname, save_folder)
        if ok:
            total_renamed += renamed_count
        else:
            errors.append(u'%s | %s' % (fname, err))
            total_renamed += renamed_count

    return total_renamed, errors


# ─────────────────────────────────────────────────────────────────────────────
# C) Create+Map — Category bazlı, tüm uygun family'lere uygula
# ─────────────────────────────────────────────────────────────────────────────

def apply_create_and_map_in_family(doc, create_map_rows, save_folder=None):
    """
    Shared/Built-in family param'lar için yeni custom TR param yaratır
    ve mevcut değerleri kopyalar.

    Seçenek B mimarisi: source_family_name yerine CATEGORY bazlı arama.
    Her MapRow için:
        - row.data['category'] veya row.Category → Revit FamilyCategory.Name
        - row.SourceParam / row.data['source_param'] → kaynak param adı
        - row.FinalTarget / row.data['final_target'] → hedef TR param adı
        - Projede o kategorideki TÜM editable family'lerde src_param varsa işle

    Bu sayede source_family_name boş olsa bile çalışır.
    source_family_name dolu gelirse sadece o family işlenir (daraltma).

    Döndürür: (total_created, error_list)
    """
    total_created = 0
    errors = []

    if not create_map_rows:
        return total_created, errors

    # ── Tüm editable family'leri category → [Family] map'ine al ─────────────
    from Autodesk.Revit.DB import FilteredElementCollector, Family

    cat_to_families = {}   # category_norm → [Family]
    name_to_family  = {}   # family_name   → Family

    for fam in FilteredElementCollector(doc).OfClass(Family).ToElements():
        try:
            if not getattr(fam, 'IsEditable', False):
                continue
            fname = fam.Name or u''
            name_to_family[fname] = fam
            cat_name = u''
            try:
                cat_name = fam.FamilyCategory.Name if fam.FamilyCategory else u''
            except Exception:
                pass
            cat_to_families.setdefault(_norm(cat_name), []).append(fam)
        except Exception:
            pass

    # ── Her MapRow için hedef family listesini belirle ───────────────────────
    # Sonra family başına gruplayarak tek EditFamily döngüsü kur

    # family_name → { src_param_norm → (src_param_orig, tgt_param, group_str, is_type) }
    family_tasks = {}

    for mr in create_map_rows:
        # Kaynak param adı
        src_name = _safe_str(
            mr.data.get('source_param_name') or
            mr.data.get('source_param') or
            getattr(mr, 'SourceParam', u'')
        ).strip()

        # Hedef TR param adı
        tgt_name = _safe_str(
            mr.data.get('target_param_name') or
            mr.data.get('final_target') or
            mr.data.get('target_param') or
            getattr(mr, 'FinalTarget', u'') or
            getattr(mr, 'ManualTarget', u'')
        ).strip()

        if not src_name or not tgt_name:
            errors.append(
                u'Create+Map | "%s" → "%s" | Kaynak veya hedef isim eksik — atlandı'
                % (src_name, tgt_name)
            )
            continue

        group_str = _safe_str(
            mr.data.get('param_group') or
            mr.data.get('parameter_group') or
            getattr(mr, 'ParameterGroup', u'')
        )
        is_type = bool(
            mr.data.get('is_type_param') or
            ((_norm(mr.data.get('binding_type', '')) == 'type') if mr.data.get('binding_type') else False) or
            (_norm(getattr(mr, 'BindingType', '')) == 'type')
        )

        # Hangi family'ler hedef?
        explicit_fname = _safe_str(
            mr.data.get('source_family_name', u'')
        ).strip()

        if explicit_fname:
            # source_family_name dolu → sadece o family
            target_families = [name_to_family[explicit_fname]] if explicit_fname in name_to_family else []
            if not target_families:
                errors.append(
                    u'Create+Map | %s | "%s" projede bulunamadı — atlandı'
                    % (src_name, explicit_fname)
                )
                continue
        else:
            # Category bazlı deneme, bulamazsa tüm family'leri tara
            cat_str = _safe_str(
                mr.data.get('category') or
                getattr(mr, 'Category', u'')
            ).strip()
            target_families = cat_to_families.get(_norm(cat_str), [])
            if not target_families:
                # Category eşleşmedi (dil farkı vb.) — tüm editable family'leri dene
                target_families = list(name_to_family.values())

        task = (src_name, tgt_name, group_str, is_type)
        for fam in target_families:
            fname = fam.Name
            family_tasks.setdefault(fname, [])
            # Aynı task iki kez eklenmesini önle
            if task not in family_tasks[fname]:
                family_tasks[fname].append(task)

    if not family_tasks:
        errors.append(u'Create+Map | Hiçbir family\'de uygulanacak görev bulunamadı (family_tasks boş)')
        return total_created, errors

    # ── Family başına EditFamily → Transaction → SaveAs → LoadFamily ─────────
    for fname, tasks in family_tasks.items():
        fam = name_to_family.get(fname)
        if fam is None:
            errors.append(u'%s | Projede bulunamadı' % fname)
            continue

        fdoc = None
        try:
            fdoc = doc.EditFamily(fam)
        except Exception as ex:
            errors.append(u'%s | EditFamily: %s' % (fname, _safe_str(ex)))
            continue

        revit_ver = _revit_version_int(fdoc)

        try:
            fmgr = fdoc.FamilyManager
            param_by_name = {}
            for fp in fmgr.Parameters:
                try:
                    param_by_name[_norm(fp.Definition.Name)] = fp
                except Exception:
                    pass
        except Exception as ex:
            errors.append(u'%s | FamilyManager: %s' % (fname, _safe_str(ex)))
            try:
                fdoc.Close(False)
            except Exception:
                pass
            continue

        tx = Transaction(fdoc, u'EGCeviri — %s Create+Map' % fname)
        tx.Start()
        created_count = 0
        tx_errors = []

        try:
            for (src_name, tgt_name, group_str, is_type) in tasks:

                # Kaynak param bu family'de var mı?
                src_fp = param_by_name.get(_norm(src_name))
                if src_fp is None:
                    tx_errors.append(
                        u'%s | "%s" bu family\'de yok — atlandı' % (fname, src_name)
                    )
                    continue

                # Hedef zaten varsa atla
                if _norm(tgt_name) in param_by_name:
                    # Sessiz atla — zaten daha önce yaratılmış olabilir
                    continue

                # StorageType
                try:
                    storage_type = src_fp.StorageType
                except Exception as ex:
                    tx_errors.append(
                        u'%s → %s | StorageType: %s' % (src_name, tgt_name, _safe_str(ex))
                    )
                    continue

                # ElementId atla
                if storage_type == StorageType.ElementId:
                    tx_errors.append(
                        u'%s | ElementId — Create+Map desteklenmiyor' % src_name
                    )
                    continue

                # AddParameter (versiyon-uyumlu)
                bpg = _resolve_group(group_str)
                new_fp, add_err = _add_parameter_compat(
                    fmgr, tgt_name, bpg, storage_type, is_type, revit_ver
                )
                if add_err or new_fp is None:
                    tx_errors.append(
                        u'%s → %s | %s' % (
                            src_name, tgt_name,
                            add_err or u'AddParameter None döndü'
                        )
                    )
                    continue

                # Değer kopyala
                if storage_type in (
                    StorageType.String, StorageType.Integer, StorageType.Double
                ):
                    _copy_param_value(src_fp, new_fp, fdoc)

                param_by_name[_norm(tgt_name)] = new_fp
                created_count += 1

            tx.Commit()

        except Exception as ex:
            try:
                tx.RollBack()
            except Exception:
                pass
            tx_errors.append(u'%s | Rollback: %s' % (fname, _safe_str(ex)))
            created_count = 0

        errors.extend(tx_errors)

        if created_count == 0:
            try:
                fdoc.Close(False)
            except Exception:
                pass
            continue

        # SaveAs + LoadFamily
        ok, err = _reload_family(doc, fdoc, fname, save_folder)
        if ok:
            total_created += created_count
        else:
            errors.append(u'%s | %s' % (fname, err))
            total_created += created_count  # param yaratıldı ama proje güncellenemedi

    return total_created, errors
