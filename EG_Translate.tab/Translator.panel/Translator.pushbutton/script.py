# -*- coding: utf-8 -*-
import os, sys, clr, datetime, hashlib
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System')
clr.AddReference('System.Windows.Forms')

import System
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Windows.Forms import FolderBrowserDialog, DialogResult, SaveFileDialog, OpenFileDialog

from pyrevit import forms, script, revit
from Autodesk.Revit.DB import *

THIS_DIR = os.path.dirname(__file__)
EXT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(THIS_DIR)))
LIB_DIR = os.path.join(EXT_DIR, 'lib')
DATA_DIR = os.path.join(EXT_DIR, 'data')
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)
from rename_engine_bridge import reload_family
from family_param_engine import apply_family_doc_params, apply_project_family_params, apply_create_and_map_in_family

from ui_text import t
from data_loader import load_translation_data, normalize_key, find_best_shared_param
from translator_engine import TranslatorEngine
from report_service import write_html_report

output = script.get_output()
doc = revit.doc
uidoc = revit.uidoc
app = __revit__.Application
XAML_PATH = os.path.join(THIS_DIR, 'ui.xaml')
FAMILY_CATEGORIES = ['Air Terminals','Cable Trays','Cable Tray Fittings','Casework','Ceilings','Communication Devices','Conduits','Conduit Fittings','Curtain Panels','Curtain Wall Mullions','Data Devices','Doors','Duct Accessories','Duct Fittings','Ducts','Electrical Equipment','Electrical Fixtures','Entourage','Fire Alarm Devices','Floors','Furniture','Furniture Systems','Generic Models','Hardscape','Lighting Devices','Lighting Fixtures','Mechanical Equipment','Parking','Pipe Accessories','Pipe Fittings','Pipes','Planting','Plumbing Fixtures','Railings','Ramps','Rebar','Roads','Roofs','Security Devices','Site','Specialty Equipment','Sprinklers','Stairs','Structural Columns','Structural Foundations','Structural Framing','Topography','Toposolid','Walls','Windows']
ARCH_FAMILY_CATEGORIES = set(['Casework','Ceilings','Curtain Panels','Curtain Wall Mullions','Doors','Floors','Furniture','Generic Models','Parking','Railings','Ramps','Roofs','Specialty Equipment','Stairs','Walls','Windows'])
MEP_FAMILY_CATEGORIES = set(['Air Terminals','Cable Trays','Cable Tray Fittings','Communication Devices','Conduits','Conduit Fittings','Data Devices','Duct Accessories','Duct Fittings','Ducts','Electrical Equipment','Electrical Fixtures','Fire Alarm Devices','Lighting Devices','Lighting Fixtures','Mechanical Equipment','Pipe Accessories','Pipe Fittings','Pipes','Plumbing Fixtures','Security Devices','Sprinklers'])
STRUCT_FAMILY_CATEGORIES = set(['Rebar','Structural Columns','Structural Foundations','Structural Framing'])
INFRA_FAMILY_CATEGORIES = set(['Cable Trays','Cable Tray Fittings','Conduits','Conduit Fittings','Pipes','Pipe Fittings','Pipe Accessories','Roads','Site','Topography','Toposolid'])
LANDSCAPE_FAMILY_CATEGORIES = set(['Entourage','Furniture','Generic Models','Hardscape','Parking','Planting','Railings','Site','Topography','Toposolid'])

def _wpf_visibility(name):
    try:
        return System.Enum.Parse(System.Windows.Visibility, name)
    except Exception:
        return 0 if name == 'Visible' else 2

def _bool(v):
    try:
        return bool(v)
    except Exception:
        return False

def _safe_text(v):
    try:
        return unicode(v)
    except Exception:
        try:
            return str(v)
        except Exception:
            return ''


def _xml_escape(v):
    s=_safe_text(v)
    s=s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
    return s

def export_rows_to_xml(path, rows):
    headers=['RowId','IsSelected','Scope','Category','Item','Current','Suggested','Manual','Final','Method','Mode','Status']
    header_cells=''.join(['<Cell ss:StyleID="sHeader"><Data ss:Type="String">%s</Data></Cell>' % _xml_escape(h) for h in headers])
    row_xml=[]
    for row in rows:
        vals=[getattr(row,'RowId',''),'1' if row.IsSelected else '0',row.Scope,row.Category,row.ItemKind,row.Current,row.Suggested,row.Manual,row.Final,row.Method,row.Mode,row.Status]
        cells=''.join(['<Cell><Data ss:Type="String">%s</Data></Cell>' % _xml_escape(v) for v in vals])
        row_xml.append('<Row>%s</Row>' % cells)
    xml = u"""<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Styles>
  <Style ss:ID="sHeader"><Font ss:Bold="1"/></Style>
 </Styles>
 <Worksheet ss:Name="Roundtrip">
  <Table>
   <Row>%s</Row>
   %s
  </Table>
 </Worksheet>
</Workbook>""" % (header_cells, ''.join(row_xml))
    f=open(path,'w')
    try:
        f.write(xml.encode('utf-8'))
    finally:
        f.close()

def _xml_local_name(tag):
    try:
        if '}' in tag:
            return tag.split('}',1)[1]
    except Exception:
        pass
    return tag

def _iter_children_by_name(node, name):
    out=[]
    try:
        for child in list(node):
            if _xml_local_name(child.tag)==name:
                out.append(child)
    except Exception:
        pass
    return out

def _cell_text(cell):
    try:
        for child in list(cell):
            if _xml_local_name(child.tag)=='Data':
                return child.text or ''
    except Exception:
        pass
    return ''

def import_manuals_from_xml(path, rows):
    try:
        import xml.etree.ElementTree as ET
    except Exception:
        return 0
    row_map={}
    for row in rows:
        rid=getattr(row,'RowId','')
        if rid:
            row_map[rid]=row
    changed=0
    tree=ET.parse(path)
    root=tree.getroot()
    worksheet=None
    for child in root.iter():
        if _xml_local_name(child.tag)=='Worksheet':
            worksheet=child
            break
    if worksheet is None:
        return 0
    table=None
    for child in list(worksheet):
        if _xml_local_name(child.tag)=='Table':
            table=child
            break
    if table is None:
        return 0
    xml_rows=_iter_children_by_name(table,'Row')
    if not xml_rows:
        return 0
    headers=[_cell_text(c).strip() for c in _iter_children_by_name(xml_rows[0],'Cell')]
    if not headers:
        return 0
    idx={}
    for i,h in enumerate(headers):
        idx[h]=i
    if 'RowId' not in idx or 'Manual' not in idx:
        return 0
    for xr in xml_rows[1:]:
        vals=[_cell_text(c) for c in _iter_children_by_name(xr,'Cell')]
        rid=vals[idx['RowId']].strip() if idx['RowId'] < len(vals) else ''
        manual=vals[idx['Manual']] if idx['Manual'] < len(vals) else ''
        row=row_map.get(rid)
        if row is None:
            continue
        if row.Manual != manual:
            row.Manual = manual
            changed += 1
    return changed

def validate_manual_rows(rows):
    errors=[]; seen={}
    for row in rows:
        manual=(row.Manual or '').strip()
        base_method=row.data.get('base_method', row.data.get('method', row.Method))
        if manual:
            row.Method='MANUAL'
            if not manual:
                row.Status='Manual empty'
            elif normalize_key(manual)==normalize_key(row.Current):
                row.Status='Manual same as current'
            else:
                # Duplicate key: aynı family + aynı kategori + aynı item_kind + aynı hedef
                # source_family_name dahil edilince farklı ailelerin aynı param adı duplicate sayılmaz
                family_key = normalize_key(
                    row.data.get('source_family_name','') or
                    row.data.get('target_doc_title','') or ''
                )
                key=(family_key, normalize_key(row.Category), normalize_key(row.ItemKind), normalize_key(manual))
                seen.setdefault(key, []).append(row)
                row.Status='Ready'
        else:
            row.Method=base_method
            row.Final=row.Suggested or row.Current
            row.data['final']=row.Final
            row.Status='Ready' if normalize_key(row.Final)!=normalize_key(row.Current) else 'Same'
        try:
            row._notify('Method'); row._notify('Final'); row._notify('Status')
        except Exception:
            pass
    for key, dup_rows in seen.items():
        if len(dup_rows) > 1:
            msg='Manual duplicate'
            for row in dup_rows:
                row.Status=msg
                try: row._notify('Status')
                except Exception: pass
            errors.append('%s | %s | %s | %s' % (key[0], key[1], key[2], key[3]))
    return errors

class Row(INotifyPropertyChanged):
    def __init__(self, data):
        self._handlers=[]; self.data=data; self._selected=bool(data.get('selected',False))
        self.RowId=data.get('row_id',''); self.Scope=data.get('scope',''); self.Category=data.get('category',''); self.ItemKind=data.get('item_kind','')
        self.Current=data.get('current',''); self.Suggested=data.get('suggested',''); self._manual=data.get('manual','')
        self.Final=data.get('final', self._manual or self.Suggested or self.Current); self.Method=data.get('method',''); self._base_method=self.Method; self.Mode=data.get('mode','Rename'); self.Status=data.get('status','')
    def add_PropertyChanged(self,h): self._handlers.append(h)
    def remove_PropertyChanged(self,h):
        if h in self._handlers: self._handlers.remove(h)
    def _notify(self,name):
        for h in self._handlers: h(self, PropertyChangedEventArgs(name))
    @property
    def IsSelected(self): return self._selected
    @IsSelected.setter
    def IsSelected(self,value):
        v=bool(value)
        if self._selected!=v: self._selected=v; self.data['selected']=v; self._notify('IsSelected')
    @property
    def Manual(self): return self._manual
    @Manual.setter
    def Manual(self,value):
        value=value or ''
        if self._manual!=value:
            self._manual=value; self.data['manual']=value; manual=value.strip(); self.Final=manual or self.Suggested or self.Current; self.data['final']=self.Final; self.Method='MANUAL' if manual else self._base_method; self.Status=('Manual empty' if value and not manual else ('Ready' if normalize_key(self.Final)!=normalize_key(self.Current) else 'Same')); self._notify('Manual'); self._notify('Final'); self._notify('Method'); self._notify('Status')

class MapRow(INotifyPropertyChanged):
    def __init__(self, data):
        self._handlers=[]; self.data=data; self._selected=bool(data.get('selected',True))
        self.SourceParam=data.get('source_param',''); self.Scope=data.get('scope',''); self.Category=data.get('category',''); self.ParamType=data.get('param_type','')
        self.ValueSample=data.get('value_sample',''); self.TargetParam=data.get('target_param',''); self._manual_target=data.get('manual_target','')
        self.FinalTarget=data.get('final_target', self._manual_target or self.TargetParam or ''); self.BindingType=data.get('binding_type',''); self.ParameterGroup=data.get('parameter_group','')
        self.Mode=data.get('mode','Create+Map'); self.Status=data.get('status','Planned'); self._base_status=self.Status
    def add_PropertyChanged(self,h): self._handlers.append(h)
    def remove_PropertyChanged(self,h):
        if h in self._handlers: self._handlers.remove(h)
    def _notify(self,name):
        for h in self._handlers: h(self, PropertyChangedEventArgs(name))
    @property
    def IsSelected(self): return self._selected
    @IsSelected.setter
    def IsSelected(self,value):
        v=bool(value)
        if self._selected!=v: self._selected=v; self.data['selected']=v; self._notify('IsSelected')
    @property
    def ManualTarget(self): return self._manual_target
    @ManualTarget.setter
    def ManualTarget(self,value):
        value=value or ''
        if self._manual_target!=value:
            self._manual_target=value; self.data['manual_target']=value
            manual=value.strip()
            self.FinalTarget=manual or self.TargetParam or ''
            self.data['final_target']=self.FinalTarget
            self.Status=('Manual empty' if value and not manual else ('Manual override' if manual else self._base_status))
            self._notify('ManualTarget'); self._notify('FinalTarget'); self._notify('Status')

class TranslatorWindow(forms.WPFWindow):
    def __init__(self, data, engine):
        forms.WPFWindow.__init__(self, XAML_PATH)
        self.data=data; self.engine=engine; self.rows=ObservableCollection[Row](); self.map_rows=ObservableCollection[MapRow](); self.all_rows=[]; self.all_map_rows=[]; self.folder=''; self.report_folder=os.path.join(os.path.expanduser('~'),'Desktop'); self.result=None; self.report_path=None; self._init_ui()
    @property
    def ui_lang(self): return 'TR' if _bool(self.UiTR.IsChecked) else 'EN'
    def _lang_from_buttons(self, group):
        for b,code in group:
            if _bool(b.IsChecked): return code
        return 'EN'
    def get_direction(self):
        src=self._lang_from_buttons([(self.SrcTR,'TR'),(self.SrcEN,'EN'),(self.SrcES,'ES'),(self.SrcPT,'PT'),(self.SrcRU,'RU')])
        tgt=self._lang_from_buttons([(self.TgtTR,'TR'),(self.TgtEN,'EN'),(self.TgtES,'ES'),(self.TgtPT,'PT'),(self.TgtRU,'RU')])
        return src,tgt
    def _init_ui(self):
        self.Title='EG Translator v2.4 PRO'; self.PlanGrid.ItemsSource=self.rows; self.ParamMapGrid.ItemsSource=self.map_rows; self.DocLabel.Text=doc.Title if doc else u'—'; self.TxtReportFolder.Text=self.report_folder
        self._all_family_categories=self._build_family_categories(); self._family_filter_items=[]
        self._set_family_filter(); self._scope_changed(None,None)
        self.ScopeFolder.Checked += self._scope_changed; self.ScopeCurrent.Checked += self._scope_changed; self.ScopeSelection.Checked += self._scope_changed
        self.UiTR.Checked += self._ui_lang_changed; self.UiEN.Checked += self._ui_lang_changed
        for b in [self.SrcTR,self.SrcEN,self.SrcES,self.SrcPT,self.SrcRU]: b.Click += self._src_click
        for b in [self.TgtTR,self.TgtEN,self.TgtES,self.TgtPT,self.TgtRU]: b.Click += self._tgt_click
        self.FilterBox.TextChanged += self.FilterBox_TextChanged
        if hasattr(self,'FamilyFilterSearchBox'): self.FamilyFilterSearchBox.TextChanged += self.FamilyFilterSearchBox_TextChanged
        try: self.LeftPanelColumn.MinWidth = 260
        except Exception: pass
        # Aile kayıt ayarları event'leri
        try:
            self.TxtFamilyPrefix.TextChanged += self._update_family_save_preview
            self.TxtFamilySuffix.TextChanged += self._update_family_save_preview
            self.TxtFamilySaveFolder.TextChanged += self._update_family_save_preview
            self._update_family_save_preview(None, None)
        except Exception: pass
        self._ui_lang_changed(None,None)
    def _build_family_categories(self):
        cats=[]; seen=set()
        def add_cat(val):
            val=(val or '').strip()
            if (not val) or val in seen: return
            seen.add(val); cats.append(val)
        for cat in FAMILY_CATEGORIES: add_cat(cat)
        for row in getattr(self.data,'category_profiles',[]) or []:
            raw=(row.get('OnerilenRevitKategorileri') or '').replace('|', ',')
            for part in raw.split(','): add_cat(part)
        cats.sort()
        return cats
    def _make_family_filter_checkbox(self, cat, checked=False):
        cb=System.Windows.Controls.CheckBox(); cb.Content=cat; cb.IsChecked=checked; cb.Margin=System.Windows.Thickness(0,2,0,2); return cb
    def _set_family_filter(self):
        self.FamilyFilterBox.Items.Clear(); self._family_filter_items=[]
        for cat in self._all_family_categories:
            cb=self._make_family_filter_checkbox(cat, False); self._family_filter_items.append(cb); self.FamilyFilterBox.Items.Add(cb)
        self._update_family_filter_count()
    def _update_family_filter_count(self):
        total=len(self._family_filter_items)
        selected=len([i for i in self._family_filter_items if _bool(getattr(i,'IsChecked',False))])
        try: self.FamilyFilterCountText.Text=u'%s/%s seçili' % (selected, total)
        except Exception: pass
    def _selected_family_filters(self):
        vals=[]
        for item in self._family_filter_items:
            if _bool(getattr(item,'IsChecked',False)): vals.append(str(item.Content))
        return vals
    def _refresh_family_filter_view(self):
        search=''
        try: search=(self.FamilyFilterSearchBox.Text or '').strip().lower()
        except Exception: pass
        self.FamilyFilterBox.Items.Clear()
        for item in self._family_filter_items:
            name=str(item.Content)
            if (not search) or (search in name.lower()): self.FamilyFilterBox.Items.Add(item)
        self._update_family_filter_count()
    def _apply_family_category_set(self, allowed):
        for item in self._family_filter_items: item.IsChecked=(str(item.Content) in allowed)
        self._refresh_family_filter_view()
    def FamilyFilterSearchBox_TextChanged(self, sender, args):
        self._refresh_family_filter_view()
    def BtnFamilyAll_Click(self, sender, args):
        for item in self._family_filter_items: item.IsChecked=True
        self._refresh_family_filter_view()
    def BtnFamilyNone_Click(self, sender, args):
        for item in self._family_filter_items: item.IsChecked=False
        self._refresh_family_filter_view()
    def BtnFamilyArch_Click(self, sender, args):
        self._apply_family_category_set(ARCH_FAMILY_CATEGORIES)
    def BtnFamilyMEP_Click(self, sender, args):
        self._apply_family_category_set(MEP_FAMILY_CATEGORIES)
    def BtnFamilyStruct_Click(self, sender, args):
        self._apply_family_category_set(STRUCT_FAMILY_CATEGORIES)
    def BtnFamilyInfra_Click(self, sender, args):
        self._apply_family_category_set(INFRA_FAMILY_CATEGORIES)
    def BtnFamilyLandscape_Click(self, sender, args):
        self._apply_family_category_set(LANDSCAPE_FAMILY_CATEGORIES)
    def _ui_lang_changed(self, sender, args):
        if sender is self.UiTR and _bool(self.UiTR.IsChecked): self.UiEN.IsChecked=False
        elif sender is self.UiEN and _bool(self.UiEN.IsChecked): self.UiTR.IsChecked=False
        lang=self.ui_lang
        self.GbUi.Header=t('group_ui',lang); self.GbDirection.Header=t('group_dir',lang); self.GbScope.Header=t('group_scope',lang); self.GbItems.Header=t('group_items',lang); self.GbFamilyFilters.Header=t('group_filters',lang); self.GbReport.Header=t('group_report',lang)
        self.ScopeCurrent.Content=t('current_document',lang); self.ScopeSelection.Content=t('selected_elements',lang); self.ScopeFolder.Content=t('folder_rfa',lang); self.BtnPickFolder.Content=t('pick_folder',lang)
        try:
            self.FamilyFilterSearchBox.ToolTip = 'Kategori ara' if lang=='TR' else 'Search category'
            self.BtnFamilyAll.Content = 'Tümü' if lang=='TR' else 'All'
            self.BtnFamilyNone.Content = 'Temizle' if lang=='TR' else 'None'
            self.BtnFamilyArch.Content = 'Mimari' if lang=='TR' else 'Arch'
            self.BtnFamilyMEP.Content = 'MEP'
            self.BtnFamilyStruct.Content = 'Statik' if lang=='TR' else 'Struct'
            self.BtnFamilyInfra.Content = 'Altyapı' if lang=='TR' else 'Infra'
            self.BtnFamilyLandscape.Content = 'Peyzaj' if lang=='TR' else 'Landscape'
        except Exception: pass
        self.BtnScan.Content=t('btn_scan',lang); self.BtnApply.Content=t('btn_apply',lang); self.BtnReport.Content=t('btn_report',lang); self.BtnCancel.Content=t('btn_cancel',lang); self.StatusText.Text=t('status_ready',lang)
        try:
            self.BtnExportExcel.Content = 'XML Dışa Aktar' if lang=='TR' else 'Export XML'
            self.BtnImportExcel.Content = 'XML İçe Al' if lang=='TR' else 'Import XML'
            self.BtnValidateManual.Content = 'Manual Kontrol' if lang=='TR' else 'Validate Manual'
        except Exception: pass
        self._update_family_filter_count()
    def _scope_changed(self, sender, args):
        vis=_wpf_visibility('Visible') if _bool(self.ScopeFolder.IsChecked) else _wpf_visibility('Collapsed'); self.BtnPickFolder.Visibility=vis; self.TxtFolder.Visibility=vis
    def _src_click(self, sender, args):
        for b in [self.SrcTR,self.SrcEN,self.SrcES,self.SrcPT,self.SrcRU]: b.IsChecked=(b==sender)
    def _tgt_click(self, sender, args):
        for b in [self.TgtTR,self.TgtEN,self.TgtES,self.TgtPT,self.TgtRU]: b.IsChecked=(b==sender)
    def BtnPickFolder_Click(self, sender, args):
        dlg=FolderBrowserDialog()
        if dlg.ShowDialog()==DialogResult.OK: self.folder=dlg.SelectedPath; self.TxtFolder.Text=self.folder

    def BtnPickFamilySaveFolder_Click(self, sender, args):
        dlg=FolderBrowserDialog()
        if dlg.ShowDialog()==DialogResult.OK:
            self.TxtFamilySaveFolder.Text=dlg.SelectedPath
            self._update_family_save_preview(None, None)

    def _update_family_save_preview(self, sender, args):
        try:
            prefix=(self.TxtFamilyPrefix.Text or '').strip()
            suffix=(self.TxtFamilySuffix.Text or '').strip()
            folder=(self.TxtFamilySaveFolder.Text or '').strip()
            folder_label=folder if folder else u'%TEMP%'
            example=u'%s\\%sAileAdı%s.rfa' % (folder_label, prefix, suffix)
            self.TxtFamilySavePreview.Text=example
        except Exception: pass

    def _get_family_save_opts(self):
        """UI'dan kayıt ayarlarını okur: (folder, prefix, suffix)"""
        try:
            folder=(self.TxtFamilySaveFolder.Text or '').strip()
            prefix=(self.TxtFamilyPrefix.Text or '').strip()
            suffix=(self.TxtFamilySuffix.Text or '').strip()
            return folder, prefix, suffix
        except Exception:
            return '', '', ''
    def BtnPickReportFolder_Click(self, sender, args):
        dlg=FolderBrowserDialog()
        if dlg.ShowDialog()==DialogResult.OK: self.report_folder=dlg.SelectedPath; self.TxtReportFolder.Text=self.report_folder; self.ReportCustom.IsChecked=True
    def _selected_item_flags(self):
        return {'room_names':_bool(self.ItRoomNames.IsChecked),'text_notes':_bool(self.ItTextNotes.IsChecked),'material_names':_bool(self.ItMaterialNames.IsChecked),'level_names':_bool(self.ItLevels.IsChecked),'view_names':_bool(self.ItViews.IsChecked),'schedule_names':_bool(self.ItSchedules.IsChecked),'sheet_names':_bool(self.ItSheets.IsChecked),'family_type_names':_bool(self.ItFamiliesTypes.IsChecked),'family_parameter_names':_bool(self.ItFamilyParams.IsChecked),'project_parameter_names':_bool(self.ItProjectParams.IsChecked),'global_parameter_names':_bool(self.ItGlobalParams.IsChecked)}
    def BtnScan_Click(self, sender, args):
        self.StatusText.Text=t('status_scanning',self.ui_lang); self.rows.Clear(); self.map_rows.Clear(); self.all_rows=[]; self.all_map_rows=[]
        src,tgt=self.get_direction(); self.engine.use_dictionary=_bool(self.OptDictionary.IsChecked); self.engine.use_api=_bool(self.OptApi.IsChecked); self.engine.use_cache=_bool(self.OptCache.IsChecked); self.engine.smart_split=_bool(self.OptSmart.IsChecked)
        try:
            raw=collect_rows(doc, uidoc, self._selected_item_flags(), src, tgt, self.engine, self.data, _bool(self.ScopeCurrent.IsChecked), _bool(self.ScopeSelection.IsChecked), _bool(self.ScopeFolder.IsChecked), self.folder, self._selected_family_filters())
            self.all_rows=[Row(r) for r in raw]; self.all_map_rows=[MapRow(m) for m in build_mapping_plan(raw, self.data)]
            self._refresh_filtered(); self._refresh_map_rows(); self.StatusText.Text=u'%s | %s satır / %s mapping' % (t('status_done',self.ui_lang), len(self.all_rows), len(self.all_map_rows))
        except Exception as ex:
            forms.alert(u'Scan error: %s' % ex); self.StatusText.Text=str(ex)
    def _refresh_filtered(self):
        q=normalize_key(self.FilterBox.Text or ''); self.rows.Clear()
        for row in self.all_rows:
            hay=u' '.join([normalize_key(row.Current),normalize_key(row.Suggested),normalize_key(row.Category),normalize_key(row.ItemKind)])
            if q and q not in hay: continue
            self.rows.Add(row)
    def _refresh_map_rows(self):
        self.map_rows.Clear()
        for r in self.all_map_rows: self.map_rows.Add(r)
    def FilterBox_TextChanged(self, sender, args): self._refresh_filtered()

    def BtnValidateManual_Click(self, sender, args):
        errs=validate_manual_rows(self.all_rows)
        if errs:
            forms.alert(u'Manual kontrol tamamlandı. Duplicate bulunan kayıt: %s' % len(errs))
        else:
            forms.alert(u'Manual kontrol tamamlandı. Duplicate yok.')
        self._refresh_filtered()

    def BtnExportExcel_Click(self, sender, args):
        if not self.all_rows:
            forms.alert(t('scan_first', self.ui_lang)); return
        dlg=SaveFileDialog(); dlg.Filter='Excel XML 2003 (*.xml)|*.xml'; dlg.DefaultExt='xml'; dlg.AddExtension=True; dlg.FileName='EG_Translator_Roundtrip.xml'
        if dlg.ShowDialog()==DialogResult.OK:
            try:
                export_rows_to_xml(dlg.FileName, self.all_rows)
                forms.alert(u'XML dışa aktarıldı\n%s' % dlg.FileName)
            except Exception as ex:
                forms.alert(u'XML dışa aktarım hatası:\n%s' % ex)

    def BtnImportExcel_Click(self, sender, args):
        if not self.all_rows:
            forms.alert(t('scan_first', self.ui_lang)); return
        dlg=OpenFileDialog(); dlg.Filter='Excel XML 2003 (*.xml)|*.xml'
        if dlg.ShowDialog()==DialogResult.OK:
            try:
                changed=import_manuals_from_xml(dlg.FileName, self.all_rows)
                errs=validate_manual_rows(self.all_rows)
                self._refresh_filtered()
                msg=u'XML içe alındı. Güncellenen satır: %s' % changed
                if not changed: msg += u'\nNot: Sadece Manual sütunu içe alınır. RowId sütunu değişmişse eşleşme olmaz.'
                if errs: msg += u'\nDuplicate kayıt: %s' % len(errs)
                forms.alert(msg)
            except Exception as ex:
                forms.alert(u'XML içe alma hatası:\n%s' % ex)

    def BtnParamSelectAll_Click(self, sender, args):
        for r in self.map_rows: r.IsSelected=True

    def BtnParamSelectNone_Click(self, sender, args):
        for r in self.map_rows: r.IsSelected=False

    def BtnParamClearManual_Click(self, sender, args):
        changed=0
        for r in self.map_rows:
            if r.IsSelected and (r.ManualTarget or '').strip():
                r.ManualTarget=''
                changed += 1
        forms.alert(u'Manual temizlendi. Güncellenen satır: %s' % changed)

    def BtnParamReplacePrefix_Click(self, sender, args):
        src=(self.ParamPrefixFromBox.Text or '').strip()
        tgt=(self.ParamPrefixToBox.Text or '').strip()
        if not src:
            forms.alert(u'Prefix From boş olamaz.'); return
        changed=0
        duplicates=[]
        seen={}
        for r in self.all_map_rows:
            final=(r.ManualTarget or r.FinalTarget or r.TargetParam or '').strip()
            if final:
                seen.setdefault(normalize_key(final), []).append(r)
        for r in self.map_rows:
            if not r.IsSelected: continue
            base=(r.ManualTarget or r.TargetParam or '').strip()
            if not base: continue
            if base.startswith(src):
                candidate=tgt + base[len(src):]
            elif normalize_key(base).startswith(normalize_key(src)):
                candidate=tgt + base[len(src):]
            else:
                continue
            r.ManualTarget=candidate
            changed += 1
        final_seen={}
        for r in self.all_map_rows:
            final=(r.FinalTarget or r.TargetParam or '').strip()
            if not final: continue
            key=(normalize_key(r.Scope), normalize_key(r.Category), normalize_key(final))
            final_seen.setdefault(key, []).append(r)
        for key, rows in final_seen.items():
            if len(rows) > 1:
                duplicates.append(u'%s | %s | %s' % (rows[0].Scope, rows[0].Category, rows[0].FinalTarget))
                for rr in rows:
                    rr.Status='Duplicate target'
        msg=u'Prefix değiştirildi. Güncellenen satır: %s' % changed
        if duplicates:
            msg += u'\nDuplicate target: %s' % len(duplicates)
        forms.alert(msg)

    def _report_base_folder(self):
        if _bool(self.ReportDocuments.IsChecked): return os.path.join(os.path.expanduser('~'),'Documents')
        if _bool(self.ReportCustom.IsChecked) and self.TxtReportFolder.Text: return self.TxtReportFolder.Text
        return os.path.join(os.path.expanduser('~'),'Desktop')
    def _create_report(self, applied=0, errors=None):
        base=self._report_base_folder()
        if not os.path.isdir(base): os.makedirs(base)
        stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S'); path=os.path.join(base, 'EG_Translator_Report_%s.html' % stamp)
        rows=[r.data.copy() for r in self.all_rows]; mappings=[m.data.copy() for m in self.all_map_rows]
        return write_html_report(path, rows, {'doc_title': doc.Title if doc else '', 'direction': '%s→%s' % self.get_direction(), 'mappings': mappings, 'applied': applied, 'errors': errors or []})
    def BtnReport_Click(self, sender, args):
        if not self.all_rows and not self.all_map_rows: forms.alert(t('scan_first',self.ui_lang)); return
        self.report_path=self._create_report(); forms.alert(u'%s\n%s' % (t('report_created',self.ui_lang), self.report_path))
    def BtnApply_Click(self, sender, args):
        if not self.all_rows and not self.all_map_rows: forms.alert(t('scan_first',self.ui_lang)); return
        has_selected_rows = bool([r for r in self.all_rows if r.IsSelected])
        has_selected_maps = bool([r for r in self.all_map_rows if getattr(r,'IsSelected',True)])
        if not has_selected_rows and not has_selected_maps: forms.alert(t('nothing_selected',self.ui_lang)); return
        self._family_save_opts=self._get_family_save_opts()
        self.result='apply'; self.Close()
    def BtnCancel_Click(self, sender, args): self.result='cancel'; self.Close()
    def BtnSelectAll_Click(self, sender, args):
        for r in self.rows: r.IsSelected=True
    def BtnSelectNone_Click(self, sender, args):
        for r in self.rows: r.IsSelected=False
    def BtnSelectChanged_Click(self, sender, args):
        for r in self.rows: r.IsSelected=normalize_key(r.Final)!=normalize_key(r.Current)

    def BtnPreviewReplacePrefix_Click(self, sender, args):
        """Current sütununda metin bul-değiştir → Manual sütununa yazar."""
        src=(self.PreviewPrefixFromBox.Text or '').strip()
        tgt=(self.PreviewPrefixToBox.Text or '').strip()
        if not src:
            forms.alert(u'From alanı boş olamaz.'); return
        changed=0; duplicates=[]
        # Duplicate kontrolü için mevcut manual değerler
        seen={}
        for r in self.all_rows:
            manual=(r.Manual or '').strip()
            if manual:
                seen.setdefault(normalize_key(manual), []).append(r)
        for r in self.all_rows:
            if not r.IsSelected: continue
            base=(r.Manual or r.Suggested or r.Current or '').strip()
            if not base: continue
            if base.startswith(src):
                candidate=tgt + base[len(src):]
            elif normalize_key(base).startswith(normalize_key(src)):
                candidate=tgt + base[len(src):]
            else:
                continue
            if normalize_key(candidate)==normalize_key(r.Current):
                continue
            r.Manual=candidate
            changed += 1
        # Duplicate kontrolü
        final_seen={}
        for r in self.all_rows:
            val=(r.Manual or r.Final or '').strip()
            if not val: continue
            key=(normalize_key(r.Scope), normalize_key(r.Category), normalize_key(val))
            final_seen.setdefault(key, []).append(r)
        for key, rows in final_seen.items():
            if len(rows)>1:
                duplicates.append(u'%s | %s | %s' % (rows[0].Scope, rows[0].Category, rows[0].Final))
                for rr in rows:
                    rr.Status='Duplicate'
        self._refresh_filtered()
        msg=u'Manual güncellendi: %s satır' % changed
        if duplicates: msg += u'\nDuplicate tespit edildi: %s' % len(duplicates)
        try: self.PreviewReplaceSummary.Text=u'✔ %s satır güncellendi' % changed
        except Exception: pass
        if duplicates: forms.alert(msg)

    def BtnPreviewClearManual_Click(self, sender, args):
        changed=0
        for r in self.rows:
            if r.IsSelected and (r.Manual or '').strip():
                r.Manual=''
                changed += 1
        self._refresh_filtered()
        try: self.PreviewReplaceSummary.Text=u'✔ %s satır temizlendi' % changed
        except Exception: pass

def _is_valid_api_object(obj):
    if obj is None:
        return False
    try:
        if hasattr(obj, 'IsValidObject'):
            return bool(obj.IsValidObject)
    except Exception:
        return False
    return True

def _safe_doc_identity(target_doc):
    title=''; path=''
    try:
        if _is_valid_api_object(target_doc):
            title=getattr(target_doc, 'Title', '') or ''
            path=getattr(target_doc, 'PathName', '') or ''
    except Exception:
        pass
    return title, path


def _build_row_id(scope, category, item_kind, current, suggested, method, extra=None):
    parts=[scope or '', category or '', item_kind or '', current or '', suggested or '', method or '']
    if extra:
        parts.extend([_safe_text(extra.get('source_path') or ''), _safe_text(extra.get('target_doc_title') or ''), _safe_text(extra.get('target_doc_path') or '')])
    raw=u'|'.join([_safe_text(p) for p in parts])
    try:
        return hashlib.md5(raw.encode('utf-8')).hexdigest()
    except Exception:
        return hashlib.md5(str(raw)).hexdigest()

def make_row(item_kind, category, current, suggested, method, target_ref=None, scope='Project', extra=None):
    target_doc = extra.get('target_doc') if extra else None
    doc_title, doc_path = _safe_doc_identity(target_doc)
    row_id=_build_row_id(scope, category, item_kind, current, suggested, method, dict(extra or {}, target_doc_title=doc_title, target_doc_path=doc_path))
    data={'row_id':row_id,'selected':normalize_key(current)!=normalize_key(suggested),'scope':scope,'category':category or '','item_kind':item_kind,'current':current or '','suggested':suggested or current or '','manual':'','final':suggested or current or '','method':method,'base_method':method,'mode':'Rename','status':'Ready' if normalize_key(current)!=normalize_key(suggested) else 'Same','target_ref':target_ref,'target_doc':target_doc,'target_doc_title':doc_title,'target_doc_path':doc_path,'source_path':extra.get('source_path') if extra else None,'can_apply':True}
    if extra: data.update(extra)
    return data

def safe_target_id(target):
    try: return target.Id.IntegerValue
    except Exception: return id(target)

def dedupe_rows(rows):
    seen=set(); out=[]
    for r in rows:
        key=(r.get('item_kind'), normalize_key(r.get('current')), r.get('category'), r.get('scope'), safe_target_id(r.get('target_ref')))
        if key in seen: continue
        seen.add(key); out.append(r)
    return out

def translate_name(engine, value, src, tgt): return engine.translate(value or '', src, tgt)


def _safe_type_name(target):
    try:
        name = getattr(target, 'Name', None)
        if name:
            return str(name)
    except Exception:
        pass
    try:
        p = target.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p:
            v = p.AsString() or p.AsValueString()
            if v:
                return str(v)
    except Exception:
        pass
    try:
        p = target.LookupParameter('Type Name')
        if p:
            v = p.AsString() or p.AsValueString()
            if v:
                return str(v)
    except Exception:
        pass
    return ''

def family_param_sample(fdoc, fam_param):
    try:
        fm=fdoc.FamilyManager
        if fm.CurrentType is None:
            for ft in fm.Types: fm.CurrentType=ft; break
        for getter in [fm.AsString, fm.AsValueString, fm.AsDouble, fm.AsInteger]:
            try:
                val=getter(fam_param)
                if val is None: continue
                if isinstance(val, float): return ('%.2f' % val)
                return str(val)
            except Exception: pass
    except Exception: pass
    return ''

def safe_group_name(definition):
    try:
        if hasattr(definition, 'GetGroupTypeId'): return str(definition.GetGroupTypeId())
        if hasattr(definition, 'ParameterGroup'): return str(definition.ParameterGroup)
    except Exception: pass
    return ''

def collect_rows(doc, uidoc, item_flags, src, tgt, engine, data, use_current, use_selection, use_folder, folder, family_filters):
    rows=[]
    if use_folder and folder:
        open_opts=OpenOptions()
        for fn in os.listdir(folder):
            if not fn.lower().endswith('.rfa'): continue
            path=os.path.join(folder, fn)
            try:
                mp=ModelPathUtils.ConvertUserVisiblePathToModelPath(path); fdoc=app.OpenDocumentFile(mp, open_opts); rows.extend(collect_document_rows(fdoc, item_flags, src, tgt, engine, data, family_filters, source_path=path)); fdoc.Close(False)
            except Exception: pass
        return dedupe_rows(rows)
    if use_selection and uidoc:
        ids=list(uidoc.Selection.GetElementIds())
        if ids: rows.extend(collect_selection_rows(doc, ids, item_flags, src, tgt, engine))
    if use_current: rows.extend(collect_document_rows(doc, item_flags, src, tgt, engine, data, family_filters))
    return dedupe_rows(rows)

def collect_document_rows(d, item_flags, src, tgt, engine, data, family_filters, source_path=None):
    rows=[]; scope='Family' if d.IsFamilyDocument else 'Project'; selected_filters=family_filters or []
    if item_flags.get('family_type_names'):
        if d.IsFamilyDocument and d.OwnerFamily:
            cat_name=d.OwnerFamily.FamilyCategory.Name if d.OwnerFamily.FamilyCategory else ''
            if (not selected_filters) or cat_name in selected_filters:
                new_name, method=translate_name(engine, d.OwnerFamily.Name, src, tgt); rows.append(make_row('Family Name', cat_name, d.OwnerFamily.Name, new_name, method, d.OwnerFamily, scope, {'target_doc':d,'source_path':source_path}))
                try:
                    for ft in d.FamilyManager.Types:
                        type_name = _safe_type_name(ft)
                        if not type_name:
                            continue
                        new2, met2=translate_name(engine, type_name, src, tgt)
                        rows.append(make_row('Type Name', cat_name, type_name, new2, met2, ft, scope, {'target_doc':d,'source_path':source_path}))
                except Exception:
                    pass
        else:
            for fam in FilteredElementCollector(d).OfClass(Family).ToElements():
                try:
                    cat_name=fam.FamilyCategory.Name if fam.FamilyCategory else ''
                    if selected_filters and cat_name not in selected_filters: continue
                    new_name, method=translate_name(engine, fam.Name, src, tgt); rows.append(make_row('Family Name', cat_name, fam.Name, new_name, method, fam, scope, {'target_doc':d,'source_path':source_path}))
                    for sid in fam.GetFamilySymbolIds():
                        sym=d.GetElement(sid)
                        if not sym:
                            continue
                        type_name = _safe_type_name(sym)
                        if not type_name:
                            continue
                        new2, met2=translate_name(engine, type_name, src, tgt)
                        rows.append(make_row('Type Name', cat_name, type_name, new2, met2, sym, scope, {'target_doc':d,'source_path':source_path}))
                except Exception: pass
    if item_flags.get('family_parameter_names') and d.IsFamilyDocument:
        try:
            cat_name=d.OwnerFamily.FamilyCategory.Name if d.OwnerFamily and d.OwnerFamily.FamilyCategory else ''
            if (not selected_filters) or cat_name in selected_filters:
                for fp in d.FamilyManager.Parameters:
                    cur=fp.Definition.Name; sug, method=translate_name(engine, cur, src, tgt); can_apply=not _bool(getattr(fp,'IsShared',False)); rows.append(make_row('Family Parameter', cat_name, cur, sug, method, fp, scope, {'can_apply':can_apply,'mode':'Rename' if can_apply else 'Create+Map','status':'Ready' if can_apply else 'Shared/Built-in → map','value_sample':family_param_sample(d, fp),'target_doc':d,'source_path':source_path,'param_scope':'FamilyManager'}))
        except Exception: pass
    if item_flags.get('family_parameter_names') and not d.IsFamilyDocument:
        for fam in FilteredElementCollector(d).OfClass(Family).ToElements():
            try:
                if not fam.IsEditable: continue
                cat_name=fam.FamilyCategory.Name if fam.FamilyCategory else ''
                if selected_filters and cat_name not in selected_filters: continue
                fdoc=d.EditFamily(fam)
                try:
                    for fp in fdoc.FamilyManager.Parameters:
                        cur=fp.Definition.Name; sug, method=translate_name(engine, cur, src, tgt)
                        is_shared=False
                        try: is_shared=bool(getattr(fp,'IsShared',False))
                        except Exception: pass
                        rows.append(make_row('Family Parameter', cat_name, cur, sug, method, fp, 'Family', {'can_apply':True,'mode':'Rename' if not is_shared else 'Create+Map','status':'Ready' if not is_shared else 'Shared/Built-in → map','value_sample':family_param_sample(fdoc, fp),'target_doc':fdoc,'source_family_name':fam.Name,'param_scope':'LoadedFamily'}))
                finally:
                    try: fdoc.Close(False)
                    except Exception: pass
            except Exception: pass
    if item_flags.get('project_parameter_names') and not d.IsFamilyDocument:
        seen=set()
        try:
            it=d.ParameterBindings.ForwardIterator(); it.Reset()
            while it.MoveNext():
                definition=it.Key; binding=it.Current; cur=definition.Name; sug, method=translate_name(engine, cur, src, tgt); cats=[]
                try:
                    for c in binding.Categories: cats.append(c.Name)
                except Exception: pass
                cat_label=', '.join(cats[:4]) or 'Project'; key=('bind', normalize_key(cur), cat_label)
                if key in seen: continue
                seen.add(key); rows.append(make_row('Project Parameter', cat_label, cur, sug, method, definition, scope, {'can_apply':False,'mode':'Create+Map','status':'BindingMap','binding_type':isinstance(binding, InstanceBinding) and 'Instance' or 'Type','parameter_group':safe_group_name(definition)}))
        except Exception: pass
        try:
            for pe in FilteredElementCollector(d).OfClass(ParameterElement).ToElements():
                cur=pe.Name; sug, method=translate_name(engine, cur, src, tgt); key=('elem', normalize_key(cur), 'Project')
                if key in seen: continue
                seen.add(key); rows.append(make_row('Project Parameter', 'Project', cur, sug, method, pe, scope, {'can_apply':False,'mode':'Create+Map','status':'ParameterElement'}))
        except Exception: pass
    if item_flags.get('global_parameter_names') and not d.IsFamilyDocument:
        try:
            for gp in FilteredElementCollector(d).OfClass(GlobalParameter).ToElements():
                sug, method=translate_name(engine, gp.Name, src, tgt); rows.append(make_row('Global Parameter', 'Project', gp.Name, sug, method, gp, scope, {'target_doc':d}))
        except Exception: pass
    if not d.IsFamilyDocument:
        if item_flags.get('material_names'):
            for e in FilteredElementCollector(d).OfClass(Material).ToElements():
                sug, met=translate_name(engine, e.Name, src, tgt); rows.append(make_row('Material', 'Materials', e.Name, sug, met, e, scope, {'target_doc':d}))
        if item_flags.get('level_names'):
            for e in FilteredElementCollector(d).OfClass(Level).ToElements():
                sug, met=translate_name(engine, e.Name, src, tgt); rows.append(make_row('Level', 'Levels', e.Name, sug, met, e, scope, {'target_doc':d}))
        if item_flags.get('view_names'):
            for e in FilteredElementCollector(d).OfClass(View).ToElements():
                try:
                    if getattr(e,'IsTemplate',False) or e.ViewType==ViewType.Schedule: continue
                except Exception: pass
                sug, met=translate_name(engine, e.Name, src, tgt); rows.append(make_row('View', 'Views', e.Name, sug, met, e, scope, {'target_doc':d}))
        if item_flags.get('schedule_names'):
            for e in FilteredElementCollector(d).OfClass(ViewSchedule).ToElements():
                sug, met=translate_name(engine, e.Name, src, tgt); rows.append(make_row('Schedule', 'Schedules', e.Name, sug, met, e, scope, {'target_doc':d}))
        if item_flags.get('sheet_names'):
            for e in FilteredElementCollector(d).OfClass(ViewSheet).ToElements():
                sug, met=translate_name(engine, e.Name, src, tgt); rows.append(make_row('Sheet', 'Sheets', e.Name, sug, met, e, scope, {'target_doc':d}))
        if item_flags.get('room_names'):
            for e in FilteredElementCollector(d).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements():
                try: cur=e.get_Parameter(BuiltInParameter.ROOM_NAME).AsString() or e.Name
                except Exception: cur=e.Name
                sug, met=translate_name(engine, cur, src, tgt); rows.append(make_row('Room Name', 'Rooms', cur, sug, met, e, scope, {'target_doc':d,'apply_via_parameter':BuiltInParameter.ROOM_NAME}))
        if item_flags.get('text_notes'):
            for e in FilteredElementCollector(d).OfClass(TextNote).ToElements():
                cur=e.Text or ''; sug, met=translate_name(engine, cur, src, tgt); rows.append(make_row('Text Note', 'Text Notes', cur, sug, met, e, scope, {'target_doc':d,'apply_text':True}))
    return rows

def collect_selection_rows(d, ids, item_flags, src, tgt, engine):
    rows=[]
    for idv in ids:
        e=d.GetElement(idv)
        if not e: continue
        try:
            cur=e.Name; sug, met=translate_name(engine, cur, src, tgt); cat=e.Category.Name if e.Category else ''
            rows.append(make_row('Selected Element', cat, cur, sug, met, e, 'Project', {'target_doc':d}))
        except Exception: pass
    return rows

def build_mapping_plan(raw_rows, data):
    out=[]; seen=set()
    for r in raw_rows:
        if r.get('item_kind') not in ('Family Parameter','Project Parameter'): continue
        target_name=find_best_shared_param(data, r.get('category'), r.get('current'), r.get('suggested')); bindrow=data.binding_by_param.get(normalize_key(target_name), {})
        key=(r.get('scope'), r.get('category'), r.get('current'), target_name)
        if key in seen: continue
        seen.add(key); out.append({'selected':True,'source_param':r.get('current',''),'scope':r.get('scope',''),'category':r.get('category',''),'param_type':r.get('param_scope', r.get('item_kind','')),'value_sample':r.get('value_sample',''),'target_param':target_name,'manual_target':'','final_target':target_name,'binding_type':bindrow.get('BindingType',''),'parameter_group':bindrow.get('ParameterGroup',''),'mode':'Create+Map','status':r.get('status')=='Ready' and 'Optional mapping' or 'Recommended mapping','source_family_name':r.get('source_family_name',''),'source_param_name':r.get('current',''),'target_param_name':target_name})
    return out

def invalid_name(val): return (not val) or (not str(val).strip())

def _resolve_target_doc_for_row(row):
    target_doc = row.data.get('target_doc')
    if _is_valid_api_object(target_doc):
        return target_doc
    return doc



def _rename_type_target(target_doc, target, final_name, row=None):
    # Family editor type rename
    try:
        if target_doc is not None and getattr(target_doc, 'IsFamilyDocument', False):
            fm = target_doc.FamilyManager
            tname = str(type(target))
            if 'FamilyType' in tname:
                try:
                    fm.CurrentType = target
                except Exception:
                    pass
                try:
                    fm.RenameCurrentType(final_name)
                    return True, None
                except Exception as ex:
                    return False, ex
    except Exception as ex:
        return False, ex

    # Project environment symbol/type rename
    # Prefer built-in type-name parameters before direct Name assignment.
    param_candidates = []
    try:
        param_candidates.append(BuiltInParameter.SYMBOL_NAME_PARAM)
    except Exception:
        pass
    try:
        param_candidates.append(BuiltInParameter.ALL_MODEL_TYPE_NAME)
    except Exception:
        pass

    for bip in param_candidates:
        try:
            p = target.get_Parameter(bip)
            if p and (not p.IsReadOnly):
                p.Set(final_name)
                return True, None
        except Exception:
            pass

    for pname in ['Type Name', 'Name']:
        try:
            p = target.LookupParameter(pname)
            if p and (not p.IsReadOnly):
                p.Set(final_name)
                return True, None
        except Exception:
            pass

    try:
        target.Name = final_name
        return True, None
    except Exception as ex:
        return False, ex

def apply_rows(selected_rows, selected_map_rows=None, family_save_folder='', family_name_prefix='', family_name_suffix=''):
    if not selected_rows and not selected_map_rows: return 0, []
    validation_errors=validate_manual_rows(selected_rows or [])
    count=0; errors=[]
    if validation_errors:
        for e in validation_errors: errors.append('Manual duplicate | %s' % e)
        return count, errors

    # ── Family Parameter satırlarını ayır ──────────────────────────────────
    # Üç kategori:
    #   1) FamilyDocument içi (can_apply=True, param_scope='FamilyManager')
    #      → apply_family_doc_params()
    #   2) Proje ailesi (can_apply=False, param_scope='LoadedFamily')
    #      → apply_project_family_params()
    #   3) Diğer her şey → mevcut grouped transaction mantığı
    family_doc_rows = []
    project_fam_rows = []
    other_rows = []

    for row in selected_rows:
        if row.ItemKind == 'Family Parameter':
            scope = row.data.get('param_scope', '')
            if scope == 'FamilyManager':
                family_doc_rows.append(row)
            elif scope == 'LoadedFamily':
                project_fam_rows.append(row)
            else:
                # can_apply kontrolüne bırak
                other_rows.append(row)
        else:
            other_rows.append(row)

    # 1) Family Editor içi parametreler
    if family_doc_rows:
        # target_doc'a göre grupla (birden fazla FamilyDoc açık olabilir)
        fdoc_groups = {}
        for row in family_doc_rows:
            td = _resolve_target_doc_for_row(row)
            fdoc_groups.setdefault(td, []).append(row)
        for fdoc_td, fd_rows in fdoc_groups.items():
            if not _is_valid_api_object(fdoc_td):
                for row in fd_rows:
                    errors.append(u'Family Parameter | %s | FamilyDoc geçersiz. Rescan yapın.' % row.Current)
                continue
            r, errs = apply_family_doc_params(fdoc_td, fd_rows)
            count += r
            errors.extend(errs)

    # 2) Proje ailesi parametreleri — EditFamily→rename→SaveAs→LoadFamily
    if project_fam_rows:
        r, errs = apply_project_family_params(
            doc, project_fam_rows,
            save_folder=family_save_folder,
            name_prefix=family_name_prefix,
            name_suffix=family_name_suffix
        )
        count += r
        errors.extend(errs)

    # 3) Diğer satırlar — orijinal mantık
    if not other_rows:
        return count, errors

    grouped={}
    for row in other_rows:
        target_doc = _resolve_target_doc_for_row(row)
        grouped.setdefault(target_doc, []).append(row)
    for target_doc, rows in grouped.items():
        if not _is_valid_api_object(target_doc):
            for row in rows:
                errors.append(u'%s | %s | Target document is no longer valid.' % (row.ItemKind, row.Current))
            continue
        tx=Transaction(target_doc, 'EG Translator v2.4 PRO Apply'); tx.Start()
        try:
            for row in rows:
                target=row.data.get('target_ref'); final=(row.Manual or row.Final or '').strip()
                if invalid_name(final) or normalize_key(final)==normalize_key(row.Current):
                    continue
                if not row.data.get('can_apply', True):
                    errors.append(u'%s | %s -> %s | Direct rename not available. Use Parameters plan.' % (row.ItemKind, row.Current, final))
                    continue
                if not _is_valid_api_object(target):
                    errors.append(u'%s | %s -> %s | Target object is no longer valid. Please rescan.' % (row.ItemKind, row.Current, final))
                    continue
                try:
                    if str(type(target)).find('FamilyParameter') >= 0:
                        target_doc.FamilyManager.RenameParameter(target, final); count += 1
                    elif row.ItemKind == 'Type Name':
                        ok, ex = _rename_type_target(target_doc, target, final, row)
                        if ok:
                            count += 1
                        else:
                            errors.append(u'%s | %s -> %s | %s' % (row.ItemKind, row.Current, final, ex or 'Type rename failed'))
                    elif isinstance(target, (Family, GlobalParameter, Material, Level, ViewSheet, ViewSchedule, View)):
                        target.Name = final; count += 1
                    elif isinstance(target, FamilySymbol):
                        ok, ex = _rename_type_target(target_doc, target, final, row)
                        if ok:
                            count += 1
                        else:
                            errors.append(u'%s | %s -> %s | %s' % (row.ItemKind, row.Current, final, ex or 'Symbol rename failed'))
                    elif isinstance(target, TextNote):
                        target.Text = final; count += 1
                    else:
                        bip=row.data.get('apply_via_parameter')
                        if bip is not None and hasattr(target,'get_Parameter'):
                            p=target.get_Parameter(bip)
                            if p and (not p.IsReadOnly):
                                p.Set(final); count += 1
                            else:
                                errors.append(u'%s | %s -> %s | Parameter is read-only or missing.' % (row.ItemKind, row.Current, final))
                        elif hasattr(target,'Name'):
                            target.Name=final; count += 1
                        else:
                            errors.append(u'%s | %s -> %s | Unsupported target type.' % (row.ItemKind, row.Current, final))
                except Exception as ex:
                    errors.append(u'%s | %s -> %s | %s' % (row.ItemKind, row.Current, final, ex))
            tx.Commit()
        except Exception as ex:
            try: tx.RollBack()
            except Exception: pass
            errors.append(str(ex))
    # ── Create+Map — tüm mapping satırlarını uygula ─────────────────────────
    if selected_map_rows:
        create_map_candidates = []
        for mr in selected_map_rows:
            def _ss(v):
                try: return unicode(v or u'')
                except: return str(v or '')
            src = (_ss(mr.data.get('source_param_name') or mr.data.get('source_param') or mr.data.get('current') or getattr(mr,'SourceParam',''))).strip()
            tgt = (_ss(mr.data.get('target_param_name') or mr.data.get('final_target') or mr.data.get('target_param') or getattr(mr,'FinalTarget',''))).strip()
            if not src or not tgt:
                errors.append(
                    u'Create+Map | "%s" → "%s" | Kaynak veya hedef isim eksik — atlandı'
                    % (src, tgt)
                )
                continue
            mr.data['source_param_name'] = src
            mr.data['target_param_name'] = tgt
            create_map_candidates.append(mr)

        if create_map_candidates:
            cm_count, cm_errors = apply_create_and_map_in_family(
                doc, create_map_candidates, save_folder=family_save_folder
            )
            count += cm_count
            errors.extend(cm_errors)
        else:
            errors.append(u'Create+Map | selected_map_rows=%d ama create_map_candidates boş' % len(selected_map_rows))

    return count, errors

try:
    data=load_translation_data(DATA_DIR); engine=TranslatorEngine(data); win=TranslatorWindow(data, engine); win.ShowDialog()
    if win.result=='apply':
        selected=[r for r in win.all_rows if r.IsSelected]
        # ObservableCollection → plain list (IronPython uyumlu)
        selected_map = []
        try:
            for mr in win.all_map_rows:
                selected_map.append(mr)
        except Exception:
            selected_map = list(win.all_map_rows) if win.all_map_rows else []
        fam_folder, fam_prefix, fam_suffix = getattr(win, '_family_save_opts', ('','',''))
        # DEBUG: boyutları logla
        _debug_info = u'DEBUG | selected=%d selected_map=%d all_map_rows=%d' % (
            len(selected), len(selected_map),
            len(win.all_map_rows) if win.all_map_rows else 0
        )
        ok, errs=apply_rows(selected, selected_map_rows=selected_map, family_save_folder=fam_folder, family_name_prefix=fam_prefix, family_name_suffix=fam_suffix)
        errs = [_debug_info] + list(errs)
        report_path=None
        if _bool(win.OptHtml.IsChecked): report_path=win._create_report(applied=ok, errors=errs); output.print_md(u'HTML report: `%s`' % report_path)
        output.print_md(u'# EG Translator v2.6 PRO'); output.print_md(u'- Applied: **%s**' % ok)
        if errs:
            output.print_md(u'## Errors')
            for e in errs[:120]: output.print_md(u'- %s' % e)
        forms.alert(u'%s\nApplied: %s%s' % (t('apply_complete', win.ui_lang), ok, report_path and ('\nReport: ' + report_path) or ''))
except Exception as ex:
    import traceback
    forms.alert(u'EG Translator v2.4 PRO error:\n%s\n\n%s' % (ex, traceback.format_exc()))
