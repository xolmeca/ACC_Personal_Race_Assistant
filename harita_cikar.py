import ast, os, re, sys

kok = sys.argv[1]
atla = {"dokumanlar", "__pycache__", ".git", "node_modules"}
anahtar = ["lfm", "elo", "rank", "drivername", "hedef_pilot", "instant_replay", "startsessiontime", "kapi"]
out = []
for yol, klasorler, dosyalar in os.walk(kok):
    klasorler[:] = [k for k in klasorler if k not in atla]
    for ad in sorted(dosyalar):
        tam = os.path.join(yol, ad)
        goreli = tam.replace(kok, "")
        boyut = os.path.getsize(tam)
        ext = os.path.splitext(ad)[1].lower()
        if ext in (".pdf", ".html", ".css") or ad.startswith("test_"):
            out.append(f"{goreli} ({boyut} bayt)")
            continue
        if ext not in (".py", ".js", ".cs", ".md", ".txt", ".json", ".ps1"):
            continue
        metin = open(tam, encoding="utf-8", errors="replace").read()
        dusuk = metin.lower()
        say = {a: dusuk.count(a) for a in anahtar if dusuk.count(a)}
        out.append(f"\n## {goreli} ({boyut} bayt) anahtar={say}")
        if ext == ".py":
            try:
                agac = ast.parse(metin)
                mod = (ast.get_docstring(agac) or "").split("\n")[0][:100]
                if mod:
                    out.append(f"  modul: {mod}")
                dugumler = [n for n in ast.walk(agac)
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                for n in sorted(dugumler, key=lambda x: x.lineno):
                    t = "class" if isinstance(n, ast.ClassDef) else "def"
                    doc = (ast.get_docstring(n) or "").split("\n")[0][:80]
                    out.append(f"  {'  ' * (n.col_offset // 4)}{t} {n.name} (L{n.lineno}) {doc}")
            except SyntaxError as e:
                out.append(f"  SYNTAX HATASI: {e}")
        elif ext in (".js", ".cs"):
            for i, satir in enumerate(metin.splitlines(), 1):
                m = re.match(r"\s*(?:public |private |internal |static |async )*(?:function|class)\s+(\w+)", satir)
                if m:
                    out.append(f"  {m.group(0).strip()[:90]} (L{i})")
open("harita.txt", "w", encoding="utf-8").write("\n".join(out))
print(len(out), "satir yazildi")
