"""Minimal SGKP JSON used by freeze tests."""

SAMPLE_SGKP_JSON = """[
  {
    "nazwa": "Aa",
    "text": "Aa, nazwa wielu rzek.",
    "rodzaj": "indywidualne",
    "ID": "01-00001",
    "typ": ["rzeka"]
  },
  {
    "nazwa": "Aal",
    "text": "Aal, ob. Rega.",
    "rodzaj": "indywidualne",
    "ID": "01-00003",
    "typ": ["odsyłacz"]
  },
  {
    "nazwa": "Aleksandrowo",
    "text": "Aleksandrowo, folw., pow. pleszewski, ob. Klenka",
    "rodzaj": "indywidualne",
    "ID": "01-00010",
    "typ": ["odsyłacz"]
  },
  {
    "nazwa": "Zbiorcze",
    "rodzaj": "zbiorcze",
    "ID": "01-00100",
    "elementy": [
      {
        "nazwa": "Anisiniowicze",
        "text": "Anisiniowicze, wś, pow. nowogródzki, 200 mieszk., ob. Dryświaty",
        "ID": "01-00100-a",
        "typ": ["odsyłacz"]
      }
    ]
  }
]
""".encode("utf-8")
