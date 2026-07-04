# -*- coding: utf-8 -*-
import datetime
def esc(s):
    s='' if s is None else str(s)
    return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
def write_html_report(report_path, rows, meta):
    total=len(rows); selected=sum(1 for r in rows if r.get('selected')); manual=sum(1 for r in rows if (r.get('manual') or '').strip()); changed=sum(1 for r in rows if (r.get('final') or '') != (r.get('current') or '')); mappings=meta.get('mappings') or []
    methods={}
    for r in rows: methods[r.get('method','')]=methods.get(r.get('method',''),0)+1
    html=[]; html.append('<!doctype html><html><head><meta charset="utf-8"><title>EG Translator Report</title><style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f6f7fb;color:#222}.card{background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px;margin-bottom:14px}table{width:100%;border-collapse:collapse;background:#fff}th,td{border:1px solid #ddd;padding:8px 10px;font-size:12px;text-align:left;vertical-align:top}th{background:#eef2ff}.pill{display:inline-block;border-radius:999px;padding:4px 10px;background:#eef2ff;margin:0 6px 6px 0;font-size:12px}</style></head><body>')
    html.append('<div class="card"><h1 style="margin-top:0">EG Translator v2.4 PRO - HTML Report</h1><p>%s</p>' % esc(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    html.append('<div><span class="pill">Document: %s</span><span class="pill">Direction: %s</span><span class="pill">Rows: %s</span><span class="pill">Selected: %s</span><span class="pill">Manual: %s</span><span class="pill">Changed: %s</span><span class="pill">Mappings: %s</span><span class="pill">Applied: %s</span></div></div>' % (esc(meta.get('doc_title','')), esc(meta.get('direction','')), total, selected, manual, changed, len(mappings), esc(meta.get('applied','0'))))
    html.append('<div class="card"><h2>Rename Preview</h2><table><thead><tr><th>Apply</th><th>Scope</th><th>Category</th><th>Item</th><th>Current</th><th>Suggested</th><th>Manual</th><th>Final</th><th>Method</th><th>Mode</th><th>Status</th></tr></thead><tbody>')
    for r in rows: html.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % ('Yes' if r.get('selected') else 'No', esc(r.get('scope','')), esc(r.get('category','')), esc(r.get('item_kind','')), esc(r.get('current','')), esc(r.get('suggested','')), esc(r.get('manual','')), esc(r.get('final','')), esc(r.get('method','')), esc(r.get('mode','')), esc(r.get('status',''))))
    html.append('</tbody></table></div>')
    if mappings:
        html.append('<div class="card"><h2>Create + Map Plan</h2><table><thead><tr><th>Apply</th><th>Source Param</th><th>Scope</th><th>Category</th><th>Value Sample</th><th>Target Param</th><th>Bind Type</th><th>Param Group</th><th>Mode</th><th>Status</th></tr></thead><tbody>')
        for m in mappings: html.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % ('Yes' if m.get('selected') else 'No', esc(m.get('source_param','')), esc(m.get('scope','')), esc(m.get('category','')), esc(m.get('value_sample','')), esc(m.get('target_param','')), esc(m.get('binding_type','')), esc(m.get('parameter_group','')), esc(m.get('mode','')), esc(m.get('status',''))))
        html.append('</tbody></table></div>')
    if meta.get('errors'):
        html.append('<div class="card"><h2>Errors</h2><ul>')
        for e in meta['errors'][:200]: html.append('<li>%s</li>' % esc(e))
        html.append('</ul></div>')
    open(report_path,'wb').write(''.join(html).encode('utf-8')); return report_path
