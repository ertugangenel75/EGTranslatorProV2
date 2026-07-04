# EGTranslatorProV2
Revit aileleri (Family) ve parametrelerini sözlük tabanlı olarak İngilizce,Portekizc,İspanyolca ve Rusça'dan Türkçe'ye çeviren, raporlayan ve standartlaştıran profesyonel bir araç.

---

# EG Translator PRO

> **Professional Revit Family Translation & Parameter Standardization Tool for pyRevit**

EG Translator PRO is a pyRevit extension designed to translate, standardize, and organize Revit Family parameters using configurable dictionaries and BIM standards.

The tool helps BIM teams maintain consistent parameter naming across different languages while supporting IFC workflows, Shared Parameters, and company BIM standards.

---

## Features

✅ Translate Revit Family Parameters

* Turkish ↔ English translation
* Dictionary-based translation engine
* Custom translation dictionaries

---

✅ Smart Parameter Recognition

* Semantic dictionary support
* Category-based profiles
* Value classification rules

---

✅ BIM Standardization

* Shared Parameter mapping
* IFC Parameter Mapping
* Category Binding Matrix
* Custom Property Set support

---

✅ Data Driven

Instead of hardcoding translations, EG Translator PRO uses editable datasets.

```
translation_dictionary.csv
semantic_dictionary.csv
standard_parameters.csv
category_profiles.csv
classify_values.csv
value_source_rules.csv
```

This allows BIM managers to customize the translation engine without modifying Python code.

---

## Folder Structure

```
EG_Translator_v2_PRO.extension
│
├── data/
│   ├── translation_dictionary.csv
│   ├── semantic_dictionary.csv
│   ├── standard_parameters.csv
│   ├── category_profiles.csv
│   ├── classify_values.csv
│   ├── shared_param_master_ref.csv
│   └── ...
│
├── lib/
│   ├── translator_engine.py
│   ├── family_param_engine.py
│   ├── rename_engine_bridge.py
│   ├── report_service.py
│   └── data_loader.py
│
└── EG_Translate.tab/
    └── Translator.panel/
        └── Translator.pushbutton/
```

---

# Translation Workflow

```
Revit Family
      │
      ▼
Read Parameters
      │
      ▼
Semantic Analysis
      │
      ▼
Dictionary Matching
      │
      ▼
Category Rules
      │
      ▼
Standard Parameter Mapping
      │
      ▼
Rename / Translate
      │
      ▼
Generate Report
```
---

# Supported Data Sources

* Translation Dictionary
* Semantic Dictionary
* Standard Parameters
* Shared Parameter Reference
* IFC Mapping Files
* Category Profiles
* Classification Rules

---

# Technology

* Python
* pyRevit
* Autodesk Revit API
* XAML UI
* CSV-based Knowledge Base

---

# Advantages

* No hardcoded translations
* Easy to extend
* BIM standard compliant
* Company customizable
* Dictionary-driven architecture
* Reusable translation engine

---

# Intended Users

* BIM Managers
* BIM Coordinators
* MEP Engineers
* Revit Content Developers
* BIM Consultants

---

# Requirements

* Autodesk Revit
* pyRevit
* Python (embedded with pyRevit)

---

# Future Roadmap

* AI-assisted translation suggestions
* Multi-language support
* Company template synchronization
* Cloud dictionary management
* IFC validation
* LLM integration
* EGBIMOTO integration

---

# License

This project is licensed under the Apache 2.0 License unless otherwise specified.

---

## About

EG Translator PRO is part of the **EGBIMOTO** ecosystem, a modular BIM automation platform focused on Revit productivity, BIM standardization, AI-assisted workflows, and engineering automation.

---


