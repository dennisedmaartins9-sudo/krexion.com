import { useState, useRef, useMemo } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Badge } from "../components/ui/badge";
import { toast } from "sonner";
import {
  Upload,
  FileSpreadsheet,
  Download,
  RefreshCw,
  Trash2,
  Filter,
  Table as TableIcon,
  AlertCircle,
  File as FileIcon,
} from "lucide-react";

const API_URL = process.env.REACT_APP_BACKEND_URL;

const MATCH_TYPES = [
  { value: "auto", label: "Auto-detect" },
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone number" },
  { value: "text", label: "Text (name, city, etc.)" },
  { value: "date", label: "Date (DOB, etc.)" },
];

const TYPE_LABELS = {
  email: "Email",
  phone: "Phone",
  text: "Text",
  date: "Date",
  auto: "Auto",
};

function countValuesForType(raw, matchType) {
  const parts = raw
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (matchType === "email") {
    return parts.filter((s) => s.includes("@")).length;
  }
  if (matchType === "phone") {
    return parts.filter((s) => (s.replace(/\D/g, "").length >= 7)).length;
  }
  return parts.length;
}

function placeholderForType(matchType) {
  switch (matchType) {
    case "phone":
      return "5551234567\n(555) 987-6543\n+1 555 111 2222";
    case "text":
      return "John\nSarah\nMichael";
    case "date":
      return "01/15/1990\n1990-01-15\n15-Jan-1990";
    case "email":
    default:
      return "alice@example.com\nbob@example.com\ncarol@example.org";
  }
}

export default function SeparateDataPage() {
  const fileInputRef = useRef(null);
  const valuesFileInputRef = useRef(null);

  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);

  const [matchColumn, setMatchColumn] = useState("");
  const [matchType, setMatchType] = useState("auto");
  const [valuesList, setValuesList] = useState("");
  const [valuesFile, setValuesFile] = useState(null);

  const [filtering, setFiltering] = useState(false);
  const [lastResult, setLastResult] = useState(null);

  const token = () => localStorage.getItem("token");

  const effectiveMatchColumn = matchColumn || preview?.match_column || preview?.email_column || "";
  const columnSuggestion = preview?.column_suggestions?.[effectiveMatchColumn] || preview?.match_type || "text";

  const effectiveMatchType = matchType === "auto"
    ? (columnSuggestion || "text")
    : matchType;

  const pastedValueCount = useMemo(
    () => countValuesForType(valuesList, effectiveMatchType),
    [valuesList, effectiveMatchType],
  );

  const handleFileChange = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;

    const ext = f.name.toLowerCase().substring(f.name.lastIndexOf("."));
    if (![".xlsx", ".xls", ".csv", ".txt"].includes(ext)) {
      toast.error("Please upload .xlsx, .xls, .csv, or .txt");
      return;
    }

    setFile(f);
    setPreview(null);
    setMatchColumn("");
    setMatchType("auto");
    setLastResult(null);
    setPreviewing(true);

    const fd = new FormData();
    fd.append("file", f);

    try {
      const r = await fetch(`${API_URL}/api/emails/preview-file`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token()}` },
        body: fd,
      });
      const data = await r.json();
      if (!r.ok) {
        toast.error(data.detail || "Failed to preview file");
        return;
      }
      setPreview(data);
      const col = data.match_column || data.email_column || "";
      setMatchColumn(col);
      setMatchType(data.match_type || "auto");
      toast.success(
        `Loaded ${data.total_rows} rows · ${data.columns.length} columns` +
          (col ? ` · suggested column: ${col} (${TYPE_LABELS[data.match_type] || data.match_type})` : ""),
      );
    } catch (err) {
      toast.error("Error: " + err.message);
    } finally {
      setPreviewing(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleValuesFileChange = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setValuesFile(f);
    toast.success(`Values file attached: ${f.name}`);
    if (valuesFileInputRef.current) valuesFileInputRef.current.value = "";
  };

  const runFilter = async () => {
    if (!file) {
      toast.error("Upload a spreadsheet first");
      return;
    }
    if (pastedValueCount === 0 && !valuesFile) {
      toast.error("Paste at least one value or upload a values file");
      return;
    }

    setFiltering(true);
    setLastResult(null);

    const fd = new FormData();
    fd.append("file", file);
    fd.append("values", valuesList);
    // Backward compat — still send emails when matching email type
    if (effectiveMatchType === "email") {
      fd.append("emails", valuesList);
    }
    if (matchColumn) fd.append("match_column", matchColumn);
    if (matchColumn) fd.append("email_column", matchColumn);
    fd.append("match_type", matchType);
    if (valuesFile) fd.append("values_file", valuesFile);

    try {
      const r = await fetch(`${API_URL}/api/emails/filter-rows`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token()}` },
        body: fd,
      });

      if (!r.ok) {
        let msg = "Filter failed";
        try {
          const data = await r.json();
          msg = data.detail || msg;
        } catch {
          // ignore
        }
        toast.error(msg);
        return;
      }

      const matched = parseInt(r.headers.get("X-Matched-Count") || "0", 10);
      const notFound = parseInt(r.headers.get("X-Not-Found-Count") || "0", 10);
      const colUsed = r.headers.get("X-Match-Column") || r.headers.get("X-Email-Column") || matchColumn;
      const typeUsed = r.headers.get("X-Match-Type") || effectiveMatchType;
      setLastResult({ matched, notFound, matchColumn: colUsed, matchType: typeUsed });

      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const cd = r.headers.get("Content-Disposition") || "";
      const m = cd.match(/filename="?([^"]+)"?/i);
      a.download = m ? m[1] : "filtered.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);

      if (matched === 0) {
        toast.warning("File downloaded, but NO rows matched your value list");
      } else {
        toast.success(
          `Downloaded ${matched} matched row${matched === 1 ? "" : "s"}` +
            (notFound > 0 ? ` · ${notFound} value(s) not found` : ""),
        );
      }
    } catch (err) {
      toast.error("Error: " + err.message);
    } finally {
      setFiltering(false);
    }
  };

  const clearAll = () => {
    setFile(null);
    setPreview(null);
    setMatchColumn("");
    setMatchType("auto");
    setValuesList("");
    setValuesFile(null);
    setLastResult(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (valuesFileInputRef.current) valuesFileInputRef.current.value = "";
  };

  const highlightColumn = effectiveMatchColumn;

  return (
    <div className="space-y-6" data-testid="separate-data-page">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Separate Data</h1>
          <p className="text-zinc-400">
            Upload your bulk file, pick any column (email, phone, name, DOB…),
            paste the values you want to keep, and download an Excel with only
            the matching full rows — every original column preserved.
          </p>
        </div>
        {(file || valuesList || valuesFile) && (
          <Button
            variant="outline"
            onClick={clearAll}
            className="border-zinc-700 text-zinc-300"
            data-testid="sd-clear-btn"
          >
            <Trash2 className="w-4 h-4 mr-2" />
            Clear
          </Button>
        )}
      </div>

      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-white flex items-center gap-2">
            <Upload className="w-5 h-5 text-blue-500" />
            1. Upload your bulk data file
          </CardTitle>
          <CardDescription>
            Excel (.xlsx/.xls) or CSV/txt with any columns — name, phone, email,
            state, DOB, etc.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-3 flex-wrap items-center">
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls,.csv,.txt"
              onChange={handleFileChange}
              className="hidden"
            />
            <Button
              onClick={() => fileInputRef.current?.click()}
              disabled={previewing}
              className="bg-purple-600 hover:bg-purple-700"
              data-testid="sd-upload-btn"
            >
              {previewing ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  Reading file…
                </>
              ) : (
                <>
                  <FileSpreadsheet className="w-4 h-4 mr-2" />
                  Choose Excel/CSV File
                </>
              )}
            </Button>

            {file && (
              <Badge className="bg-zinc-700 text-zinc-100 gap-1">
                <FileIcon className="w-3 h-3" />
                {file.name}
              </Badge>
            )}
            {preview && (
              <>
                <Badge className="bg-blue-700">{preview.total_rows} rows</Badge>
                <Badge className="bg-blue-700">{preview.columns.length} columns</Badge>
                {effectiveMatchColumn && (
                  <Badge className="bg-green-700">
                    suggested: {effectiveMatchColumn} ({TYPE_LABELS[preview.match_type] || preview.match_type})
                  </Badge>
                )}
              </>
            )}
          </div>

          {preview && (
            <div className="flex gap-3 flex-wrap items-center">
              <label className="text-zinc-300 text-sm">Match column:</label>
              <select
                value={matchColumn}
                onChange={(e) => setMatchColumn(e.target.value)}
                className="bg-zinc-800 border border-zinc-700 text-white text-sm rounded px-2 py-1"
                data-testid="sd-match-column-select"
              >
                {preview.columns.map((c) => (
                  <option key={c} value={c}>
                    {c}
                    {preview.column_suggestions?.[c]
                      ? ` (${TYPE_LABELS[preview.column_suggestions[c]] || preview.column_suggestions[c]})`
                      : ""}
                  </option>
                ))}
              </select>

              <label className="text-zinc-300 text-sm">Match as:</label>
              <select
                value={matchType}
                onChange={(e) => setMatchType(e.target.value)}
                className="bg-zinc-800 border border-zinc-700 text-white text-sm rounded px-2 py-1"
                data-testid="sd-match-type-select"
              >
                {MATCH_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
              <span className="text-zinc-500 text-xs">
                Auto uses column header + sample data. Phone ignores formatting;
                text is case-insensitive; dates normalize common formats.
              </span>
            </div>
          )}

          {preview && preview.preview_rows?.length > 0 && (
            <div className="border border-zinc-800 rounded-md overflow-hidden">
              <div className="bg-zinc-800/70 px-3 py-2 text-xs text-zinc-300 flex items-center gap-2">
                <TableIcon className="w-3 h-3" />
                Preview — first {preview.preview_rows.length} rows
              </div>
              <div className="max-h-72 overflow-auto">
                <table className="w-full text-xs text-zinc-200">
                  <thead className="bg-zinc-800/50 sticky top-0">
                    <tr>
                      {preview.columns.map((c) => (
                        <th
                          key={c}
                          className={`text-left px-3 py-2 whitespace-nowrap font-medium ${
                            c === highlightColumn ? "text-green-400" : "text-zinc-300"
                          }`}
                        >
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.preview_rows.map((r, i) => (
                      <tr key={i} className={i % 2 ? "bg-zinc-900" : "bg-zinc-900/60"}>
                        {preview.columns.map((c) => (
                          <td key={c} className="px-3 py-1.5 whitespace-nowrap text-zinc-200">
                            {String(r[c] ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-white flex items-center gap-2">
            <Filter className="w-5 h-5 text-blue-500" />
            2. Paste values to keep
          </CardTitle>
          <CardDescription>
            One value per line (comma/semicolon also OK). Matching rows export
            with every column intact.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            value={valuesList}
            onChange={(e) => setValuesList(e.target.value)}
            placeholder={placeholderForType(effectiveMatchType)}
            className="bg-zinc-800 border-zinc-700 text-white h-40 font-mono text-sm"
            data-testid="sd-values-list"
          />

          <div className="flex gap-3 flex-wrap items-center">
            <input
              ref={valuesFileInputRef}
              type="file"
              accept=".txt,.csv,.xlsx,.xls"
              onChange={handleValuesFileChange}
              className="hidden"
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => valuesFileInputRef.current?.click()}
              className="border-zinc-700 text-zinc-300"
              data-testid="sd-values-file-btn"
            >
              <Upload className="w-4 h-4 mr-2" />
              Upload values file (optional)
            </Button>
            {valuesFile && (
              <Badge className="bg-zinc-700 text-zinc-100">{valuesFile.name}</Badge>
            )}
          </div>

          <div className="flex items-center justify-between flex-wrap gap-3">
            <span className="text-zinc-400 text-sm">
              {pastedValueCount} value{pastedValueCount === 1 ? "" : "s"} in list
              {valuesFile ? " + values file attached" : ""}
              {matchType === "auto" && effectiveMatchColumn
                ? ` · matching as ${TYPE_LABELS[effectiveMatchType] || effectiveMatchType}`
                : ""}
            </span>
            <Button
              onClick={runFilter}
              disabled={filtering || !file || (pastedValueCount === 0 && !valuesFile)}
              className="bg-green-600 hover:bg-green-700"
              data-testid="sd-filter-btn"
            >
              {filtering ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  Filtering…
                </>
              ) : (
                <>
                  <Download className="w-4 h-4 mr-2" />
                  Filter &amp; Download Excel
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {lastResult && (
        <Card
          className={`border ${
            lastResult.matched > 0
              ? "bg-green-900/20 border-green-700"
              : "bg-yellow-900/20 border-yellow-700"
          }`}
          data-testid="sd-result-card"
        >
          <CardContent className="py-5">
            <div className="flex items-start gap-3">
              {lastResult.matched > 0 ? (
                <Download className="w-5 h-5 text-green-400 mt-0.5" />
              ) : (
                <AlertCircle className="w-5 h-5 text-yellow-400 mt-0.5" />
              )}
              <div className="text-sm text-zinc-200 space-y-1">
                <p>
                  <strong className="text-white">{lastResult.matched}</strong> matching row(s) exported.{" "}
                  <strong className="text-white">{lastResult.notFound}</strong> value(s) from your list were not found.
                </p>
                <p className="text-zinc-400 text-xs">
                  Column{" "}
                  <span className="text-zinc-200 font-mono">{lastResult.matchColumn || "(auto)"}</span>
                  {" · "}
                  type{" "}
                  <span className="text-zinc-200 font-mono">
                    {TYPE_LABELS[lastResult.matchType] || lastResult.matchType}
                  </span>
                  . Download has 3 sheets: Matched Rows, Summary, Not Found.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
