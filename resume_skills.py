"""Local PDF skill suggestions and conservative matching against supplied requirements."""
from __future__ import annotations

import io
import re

from core import MAX_CV_UPLOAD_BYTES

SKILLS = {
    "C#": r"(?<!\w)c\s*#|\bc[ -]?sharp\b",
    "C": r"(?<![\w.])(?-i:C)(?![\w#+])", "F#": r"(?<!\w)f\s*#",
    "C++": r"(?<!\w)c\+\+", "Java": r"\bjava\b", "Python": r"\bpython\b",
    "JavaScript": r"\bjavascript\b|\bjs\b", "TypeScript": r"\btypescript\b|\bts\b",
    ".NET": r"(?<!\w)\.net\b|\bdotnet\b",
    "ASP.NET Core": r"\basp\.?net\s*core\b", "ASP.NET": r"\basp\.?net\b(?!\s*core)",
    "MVC": r"\bmvc\b|model.view.controller", "Razor": r"\brazor\b", "Blazor": r"\bblazor\b",
    "Entity Framework Core": r"\bentity framework(?:\s*core)?\b|\bef\s*core\b", "Dapper": r"\bdapper\b",
    "LINQ": r"\blinq\b", "SignalR": r"\bsignalr\b", "WPF": r"\bwpf\b",
    "Windows Forms": r"\bwinforms\b|windows forms", ".NET MAUI": r"\bmaui\b",
    "SQL": r"\bsql\b", "SQL Server": r"\bsql server\b|\bmssql\b",
    "PostgreSQL": r"\bpostgres(?:ql)?\b", "MySQL": r"\bmysql\b", "SQLite": r"\bsqlite\b",
    "MongoDB": r"\bmongodb\b", "Redis": r"\bredis\b", "HTML": r"\bhtml5?\b",
    "PL/SQL": r"\bpl\s*/\s*sql\b",
    "CSS": r"\bcss3?\b", "Tailwind CSS": r"\btailwind\b", "Bootstrap": r"\bbootstrap\b",
    "React": r"\breact(?:\.js|js)?\b", "Next.js": r"\bnext\.?js\b", "Angular": r"\bangular\b",
    "Vue": r"\bvue(?:\.js|js)?\b", "Node.js": r"\bnode\.?js\b", "Express": r"\bexpress(?:\.js|js)?\b",
    "PHP": r"\bphp\b", "Laravel": r"\blaravel\b", "Django": r"\bdjango\b", "FastAPI": r"\bfastapi\b",
    "Spring Boot": r"\bspring boot\b", "Flutter": r"\bflutter\b", "Dart": r"\bdart\b",
    "REST APIs": r"\brestful\b|\brest\s*apis?\b", "GraphQL": r"\bgraphql\b",
    "Object-oriented programming": r"\boop\b|object.oriented(?:\s+programming)?",
    "Git": r"\bgit\b", "GitHub": r"\bgithub\b", "GitHub Actions": r"github actions",
    "Docker": r"\bdocker\b", "Kubernetes": r"\bkubernetes\b", "Azure": r"\bazure\b",
    "AWS": r"\baws\b|amazon web services", "Google Cloud": r"\bgcp\b|google cloud",
    "CI/CD": r"\bci\s*/\s*cd\b|continuous integration|continuous delivery",
    "Unit testing": r"\bunit test(?:ing|s)?\b", "xUnit": r"\bxunit\b", "NUnit": r"\bnunit\b",
    "Postman": r"\bpostman\b", "Figma": r"\bfigma\b", "Agile": r"\bagile\b", "Scrum": r"\bscrum\b",
    "Visual Studio": r"\bvisual studio\b(?!\s*code)", "Visual Studio Code": r"\bvisual studio code\b|\bvs\s*code\b",
    "NuGet": r"\bnuget\b", "Swagger / OpenAPI": r"\bswagger\b|\bopenapi\b",
    "Claude": r"\bclaude\b", "ChatGPT": r"\bchatgpt\b", "Gemini": r"\bgemini\b",
}


def detect_skills(text: str) -> list[str]:
    # Ignore URLs/mail addresses so technology-looking domains do not become skills.
    text = re.sub(r"https?://\S+|\bwww\.\S+|\S+@\S+", " ", text)
    return [name for name, pattern in SKILLS.items() if re.search(pattern, text, re.I)]


def resume_skill_text(text: str) -> str:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(
        r"^\s*(?:technical skills|skills|technical competencies|technical proficiencies|tech stack)\s*(?::|$)", line, re.I)), None)
    chosen = lines if start is None else lines[start:]
    result = []
    learning = False
    for i, line in enumerate(chosen):
        if start is not None and i and re.fullmatch(r"\s*(?:professional experience|work experience|project experience|experience|education|projects|selected projects|relevant projects|personal projects|certifications|awards|references)\s*", line, re.I):
            break
        if re.match(r"\s*(?:currently learning|learning|aspiring to learn)\s*:", line, re.I):
            learning = True
            continue
        if learning and ":" not in line:
            continue
        learning = False
        result.append(line)
    return "\n".join(result)


def pdf_skills(raw: bytes) -> list[str]:
    if not raw.startswith(b"%PDF-") or len(raw) > MAX_CV_UPLOAD_BYTES:
        raise ValueError("Choose an existing PDF CV up to 20 MB")
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("Use a PDF that can be opened without a password")
        if len(reader.pages) > 20:
            raise ValueError("Resume skill extraction supports up to 20 pages")
        text = "\n".join((page.extract_text() or "")[:50000] for page in reader.pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The CV text could not be read. Use a text-based PDF or enter the skills manually") from exc
    if not text.strip():
        raise ValueError("No readable CV text found. Scanned PDFs need OCR first; you can still enter skills manually")
    return detect_skills(resume_skill_text(text))


def match_required_skills(available: list[str], requirements: str) -> list[str]:
    """Intersect resume evidence with supplied requirements; exclude obvious optional blocks."""
    required_parts = []
    optional = False
    for line in requirements.splitlines():
        line = line.strip()
        if re.match(r"^(?:nice.to.have|preferred(?: qualifications| skills)?|optional(?: skills)?|bonus)(?:\s*[:\-]|\s*$)", line, re.I):
            optional = True
            continue
        if re.match(r"^(?:required(?: skills| qualifications)?|requirements|must.have|minimum qualifications)(?:\s*[:\-]|\s*$)", line, re.I):
            optional = False
        if optional:
            continue
        if re.search(r"preferred|optional|nice.to.have|\ba plus\b", line, re.I) and not re.search(r"\brequired\b|\bmust\b", line, re.I):
            continue
        for part in re.split(r"[;,]", line):
            if re.search(r"nice.to.have|\bpreferred\b|\boptional\b|\bbonus\b|\ba plus\b|not (?:required|needed|necessary)|\bno\b.*\brequired\b", part, re.I):
                continue
            required_parts.append(part)
    mentioned = set(detect_skills("\n".join(required_parts)))
    return [skill for skill in available if skill in mentioned]
