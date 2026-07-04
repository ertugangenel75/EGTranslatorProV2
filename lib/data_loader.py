# -*- coding: utf-8 -*-
import os, csv, re
LANG_COLS={'TR':['Terim_TR','TR_Name','ParametreAdı','StandartParametre_TR'],'EN':['StandartKarsilik_EN','EN_Name','StandartParametre_EN'],'ES':['Terim_ES'],'PT':['Terim_PT'],'RU':['Terim_RU']}
CATEGORY_PREFIX={'Doors':u'Kapi','Windows':u'Pencere','Furniture':u'Mobilya','Generic Models':u'Genel','Mechanical Equipment':u'Mekanik','Electrical Fixtures':u'Elektrik','Lighting Fixtures':u'Aydinlatma','Plumbing Fixtures':u'Sihhi','Walls':u'Duvar','Floors':u'Doseme','Roofs':u'Cati','Rooms':u'Mahal','Project Information':u'Proje','Project':u'Proje'}
class TranslationData(object):
    def __init__(self):
        self.exact={}; self.tokens={}; self.standard={}; self.category_profiles=[]; self.shared_params={}; self.shared_groups={}; self.ifc_map={}; self.custom_psets=[]; self.binding_rows=[]; self.binding_by_param={}
    def get_exact(self, src, tgt, text): return self.exact.get((src, tgt, normalize_key(text)))
    def get_token(self, src, tgt, token): return self.tokens.get((src, tgt, normalize_key(token)))
def normalize_key(value):
    if value is None: return ''
    try:
        if not isinstance(value, str): value = str(value)
    except Exception: value = str(value)
    value=value.strip().lower(); value=re.sub(r'\s+', ' ', value)
    return value
def sanitize_ascii(value):
    value=normalize_key(value)
    for a,b in [(u'ç',u'c'),(u'ğ',u'g'),(u'ı',u'i'),(u'ö',u'o'),(u'ş',u's'),(u'ü',u'u')]: value=value.replace(a,b)
    value=re.sub(r'[^0-9a-z ]+',' ',value); value=re.sub(r'\s+',' ',value).strip(); return value
def _first(row,names):
    for name in names:
        if name in row and row[name]: return row[name]
    return ''
def _read_text(path):
    raw=open(path,'rb').read()
    for enc in ('utf-8-sig','utf-8','cp1254','latin-1'):
        try: return raw.decode(enc)
        except Exception: pass
    return raw.decode('utf-8','ignore')
def _read_csv(path): return list(csv.DictReader(_read_text(path).splitlines()))
def _camel_join(text): return ''.join([p[:1].upper()+p[1:] for p in re.split(r'[^0-9A-Za-zÇĞİÖŞÜçğıöşü]+', text or '') if p])
def parse_shared_parameter_master(path, td):
    if not os.path.exists(path): return
    for line in _read_text(path).splitlines():
        if not line or line.startswith('#'): continue
        parts=line.split('\t')
        if parts[0]=='GROUP' and len(parts)>=3: td.shared_groups[parts[1]]=parts[2]
        elif parts[0]=='PARAM' and len(parts)>=10:
            td.shared_params[normalize_key(parts[2])]={'guid':parts[1],'name':parts[2],'datatype':parts[3],'group_id':parts[5],'group_name':td.shared_groups.get(parts[5],''),'visible':parts[6],'description':parts[7],'user_modifiable':parts[8],'hide_when_no_value':parts[9]}
def parse_ifc_mapping(path, td):
    if not os.path.exists(path): return
    for line in _read_text(path).splitlines():
        if not line or line.startswith('#'): continue
        parts=line.split('\t')
        if len(parts)>=3 and parts[0] != '#Pset': td.ifc_map[(normalize_key(parts[0]), normalize_key(parts[1]))]=parts[2]
def parse_custom_psets(path, td):
    if not os.path.exists(path): return
    current=None
    for line in _read_text(path).splitlines():
        if not line or line.startswith('#'): continue
        if line.startswith('PropertySet:'):
            parts=[p for p in line.split('\t') if p]; current=parts[1] if len(parts)>1 else None
        elif current and line.startswith('\t'):
            parts=[p for p in line.split('\t') if p]
            if len(parts)>=3: td.custom_psets.append({'pset':current,'property':parts[0],'datatype':parts[1],'parameter':parts[2]})
def parse_binding_csv(path, td):
    if not os.path.exists(path): return
    td.binding_rows=_read_csv(path)
    for row in td.binding_rows: td.binding_by_param[normalize_key(row.get('ParameterName',''))]=row
def _bind_dictionary_row(td,row):
    for src in ['TR','EN','ES','PT','RU']:
        src_text=_first(row, LANG_COLS.get(src,[]))
        if not src_text: continue
        for tgt in ['TR','EN','ES','PT','RU']:
            if tgt==src: continue
            tgt_text=_first(row, LANG_COLS.get(tgt,[]))
            if tgt_text:
                td.exact[(src,tgt,normalize_key(src_text))]=tgt_text
                if ' ' not in src_text.strip() and ' ' not in tgt_text.strip(): td.tokens[(src,tgt,normalize_key(src_text))]=tgt_text
def load_translation_data(data_dir):
    td=TranslationData()
    for fn in ['translation_dictionary.csv','semantic_dictionary.csv','standard_parameters.csv','shared_param_master_ref.csv']:
        path=os.path.join(data_dir,fn)
        if os.path.exists(path):
            for row in _read_csv(path):
                _bind_dictionary_row(td,row)
                tr=_first(row,LANG_COLS['TR']); en=_first(row,LANG_COLS['EN'])
                if tr and en: td.standard[normalize_key(tr)]={'TR':tr,'EN':en}; td.standard[normalize_key(en)]={'TR':tr,'EN':en}
    cp=os.path.join(data_dir,'category_profiles.csv')
    if os.path.exists(cp): td.category_profiles=_read_csv(cp)
    parse_shared_parameter_master(os.path.join(data_dir,'TR_BIM_SharedParameters_MASTER_QA_CSB2026.txt'), td)
    parse_ifc_mapping(os.path.join(data_dir,'TR_BIM_IFC_ParameterMapping_QA_CSB2026.txt'), td)
    parse_custom_psets(os.path.join(data_dir,'TR_BIM_IFC_CustomPsets_QA_CSB2026.txt'), td)
    parse_binding_csv(os.path.join(data_dir,'TR_BIM_Revit_Category_Binding_Import.csv'), td)
    return td
def find_best_shared_param(td, category_name, source_name, translated_name=''):
    names=[source_name, translated_name]
    for name in names:
        nk=normalize_key(name)
        if nk in td.shared_params: return td.shared_params[nk]['name']
        if nk in td.binding_by_param: return td.binding_by_param[nk]['ParameterName']
    category_name=category_name or 'Project'; prefix=CATEGORY_PREFIX.get(category_name, _camel_join(category_name) or 'Genel')
    common={'doors':{'firerating':'TR_KapiYangınSinifi','thermaltransmittance':'TR_KapiUDegeri','acousticrating':'TR_KapiSesYalitim','reference':'TR_KapiTipi','height':'TR_KapiYukseklik','width':'TR_KapiGenislik','rough height':'TR_KapiKabaYukseklik','rough width':'TR_KapiKabaGenislik'},'windows':{'thermaltransmittance':'TR_PencereUDegeri','acousticrating':'TR_PencereSesYalitim','reference':'TR_PencereTipi','height':'TR_PencereYukseklik','width':'TR_PencereGenislik'},'walls':{'firerating':'TR_DuvarREI','thermaltransmittance':'TR_DuvarUDegeri','acousticrating':'TR_DuvarSesYalitim'},'floors':{'firerating':'TR_DosemeREI','thermaltransmittance':'TR_DosemeUDegeri','acousticrating':'TR_DosemeSesYalitim'},'roofs':{'firerating':'TR_CatiREI','thermaltransmittance':'TR_CatiUDegeri','reference':'TR_CatiTipi'},'rooms':{'name':'TR_MahalAdi','number':'TR_MahalKodu','category':'TR_MahalFonksiyonu'}}
    catkey=sanitize_ascii(category_name)
    for name in names:
        nk=sanitize_ascii(name)
        if catkey in common and nk in common[catkey]: return common[catkey][nk]
    translated=translated_name or source_name or 'Parametre'; candidate='TR_%s%s' % (prefix, _camel_join(translated))
    nk=normalize_key(candidate)
    if nk in td.shared_params: return td.shared_params[nk]['name']
    needle=set(sanitize_ascii(translated).split()); best=None; best_score=0
    for row in td.binding_rows:
        cats=sanitize_ascii(row.get('RevitCategories',''))
        if catkey and catkey not in cats and catkey not in sanitize_ascii(row.get('CategorySet','')): continue
        pname=row.get('ParameterName',''); score=len(needle.intersection(set(sanitize_ascii(pname).split())))
        if score>best_score: best=pname; best_score=score
    return best or candidate
