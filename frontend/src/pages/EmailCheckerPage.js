import { useState, useRef, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Badge } from "../components/ui/badge";
import { Progress } from "../components/ui/progress";
import { toast } from "sonner";
import {
  Upload,
  UserCheck,
  UserX,
  Download,
  RefreshCw,
  Image,
  ImageOff,
  Copy,
  Trash2,
  FileSpreadsheet,
  File,
  Link2,
  CheckCircle,
  AlertCircle,
  LogOut,
  UserCog,
} from "lucide-react";

const API_URL = process.env.REACT_APP_BACKEND_URL;

export default function EmailCheckerPage() {
  const [emailInput, setEmailInput] = useState("");
  const [checking, setChecking] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [results, setResults] = useState(null);
  const [withPic, setWithPic] = useState([]);
  const [withoutPic, setWithoutPic] = useState([]);
  const [googleConnected, setGoogleConnected] = useState(false);
  const [googleEmail, setGoogleEmail] = useState(null);
  const [checkingGoogle, setCheckingGoogle] = useState(true);
  const [disconnecting, setDisconnecting] = useState(false);

  // Mode: "gmail" (recommended) | "public" | "contacts_only" | "all"
  const [checkMode, setCheckMode] = useState("gmail");

  // Original uploaded file data preserved for export
  const [originalRows, setOriginalRows] = useState([]);      // list of row dicts
  const [originalColumns, setOriginalColumns] = useState([]); // column names in order
  const [emailColumn, setEmailColumn] = useState(null);       // detected email column
  const [uploadedFilename, setUploadedFilename] = useState(null);

  const fileInputRef = useRef(null);

  useEffect(() => {
    checkGoogleStatus();

    // Listen for Google OAuth callback
    const handleMessage = (event) => {
      if (event.data?.type === "google_auth_success") {
        toast.success("Google account connected!");
        checkGoogleStatus();
      }
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  const checkGoogleStatus = async () => {
    setCheckingGoogle(true);
    try {
      const token = localStorage.getItem("token");
      const response = await fetch(`${API_URL}/api/google/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.ok) {
        const data = await response.json();
        setGoogleConnected(!!data.connected);
        setGoogleEmail(data.email || null);
      }
    } catch (error) {
      console.error("Error checking Google status:", error);
    } finally {
      setCheckingGoogle(false);
    }
  };

  const connectGoogle = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await fetch(`${API_URL}/api/google/auth-url`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!response.ok) {
        const data = await response.json();
        toast.error(data.detail || "Failed to get auth URL");
        return;
      }

      const data = await response.json();
      window.open(
        data.auth_url,
        "google_auth",
        "width=500,height=650,scrollbars=yes"
      );
    } catch (error) {
      toast.error("Error connecting Google: " + error.message);
    }
  };

  const disconnectGoogle = async () => {
    setDisconnecting(true);
    try {
      const token = localStorage.getItem("token");
      const response = await fetch(`${API_URL}/api/google/disconnect`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.ok) {
        toast.success("Google account disconnected");
        setGoogleConnected(false);
        setGoogleEmail(null);
      } else {
        toast.error("Failed to disconnect");
      }
    } catch (error) {
      toast.error("Error disconnecting: " + error.message);
    } finally {
      setDisconnecting(false);
    }
  };

  const switchGoogleAccount = async () => {
    await disconnectGoogle();
    // After disconnect, immediately open the connect popup for a different account
    setTimeout(() => connectGoogle(), 300);
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const validExtensions = [".xlsx", ".xls", ".csv", ".txt"];
    const ext = file.name.toLowerCase().substring(file.name.lastIndexOf("."));

    if (!validExtensions.includes(ext)) {
      toast.error("Please upload .xlsx, .xls, .csv, or .txt file");
      return;
    }

    setUploading(true);
    const token = localStorage.getItem("token");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${API_URL}/api/emails/upload-file`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });

      const data = await response.json();

      if (response.ok) {
        setEmailInput(data.emails.join("\n"));
        setOriginalRows(data.rows || []);
        setOriginalColumns(data.columns || []);
        setEmailColumn(data.email_column || null);
        setUploadedFilename(data.filename || file.name);
        toast.success(
          `Loaded ${data.count} emails from ${file.name}` +
            (data.email_column ? ` (email column: ${data.email_column})` : "")
        );
      } else {
        toast.error(data.detail || "Failed to parse file");
      }
    } catch (error) {
      toast.error("Error uploading file: " + error.message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const checkEmails = async () => {
    const emails = emailInput
      .split(/[\n,;]+/)
      .map((e) => e.trim().toLowerCase())
      .filter((e) => e && e.includes("@"));

    if (emails.length === 0) {
      toast.error("Please enter at least one valid email");
      return;
    }

    if (checkMode === "contacts_only" && !googleConnected) {
      toast.error("'Contacts only' mode requires a connected Google account.");
      return;
    }

    if (checkMode === "gmail" && !googleConnected) {
      toast.warning(
        "Gmail mode works best with Google connected — results may miss photos you see in Gmail compose."
      );
    }

    setChecking(true);
    setProgress(0);
    setWithPic([]);
    setWithoutPic([]);

    const token = localStorage.getItem("token");

    try {
      const response = await fetch(`${API_URL}/api/emails/check-profile-pics`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ emails, check_mode: checkMode }),
      });

      if (!response.ok) {
        throw new Error("Failed to check emails");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      let withPicList = [];
      let withoutPicList = [];
      let processed = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const text = decoder.decode(value);
        const lines = text.split("\n").filter((l) => l.trim());

        for (const line of lines) {
          try {
            const data = JSON.parse(line);
            if (data.type === "progress") {
              processed = data.processed;
              setProgress(Math.round((processed / emails.length) * 100));
            } else if (data.type === "result") {
              if (data.has_pic) {
                withPicList.push(data);
                setWithPic([...withPicList]);
              } else {
                withoutPicList.push(data);
                setWithoutPic([...withoutPicList]);
              }
            } else if (data.type === "complete") {
              setResults({
                total: data.total,
                with_pic: data.with_pic,
                without_pic: data.without_pic,
                used_google_api: data.used_google_api,
                check_mode: data.check_mode,
              });
            }
          } catch (e) {
            // Skip invalid JSON lines
          }
        }
      }

      toast.success(`Checked ${emails.length} emails!`);
    } catch (error) {
      toast.error("Error checking emails: " + error.message);
    } finally {
      setChecking(false);
      setProgress(100);
    }
  };

  const copyEmails = (list, type) => {
    const emails = list.map((r) => r.email).join("\n");
    navigator.clipboard.writeText(emails);
    toast.success(`Copied ${list.length} ${type} emails!`);
  };

  const downloadExcel = async () => {
    const token = localStorage.getItem("token");

    // Build results dict keyed by email
    const resultsDict = {};
    for (const r of withPic) {
      resultsDict[r.email] = {
        has_pic: true,
        pic_url: r.pic_url || "",
        method: r.method || "",
      };
    }
    for (const r of withoutPic) {
      resultsDict[r.email] = {
        has_pic: false,
        pic_url: "",
        method: r.method || "",
        note: r.note || "",
      };
    }

    try {
      const response = await fetch(`${API_URL}/api/emails/download-results`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          rows: originalRows,
          columns: originalColumns,
          email_column: emailColumn,
          results: resultsDict,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to generate Excel");
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const baseName = uploadedFilename
        ? uploadedFilename.replace(/\.[^.]+$/, "")
        : "email_check_results";
      a.download = `${baseName}_checked.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Excel file downloaded (original columns preserved)!");
    } catch (error) {
      toast.error("Error downloading: " + error.message);
    }
  };

  const downloadCSV = (list, filename) => {
    const csv =
      "Email,Has Profile Pic,Profile URL\n" +
      list.map((r) => `${r.email},${r.has_pic},${r.pic_url || ""}`).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const removeEmail = (email, hasPic) => {
    if (hasPic) {
      setWithPic(withPic.filter((r) => r.email !== email));
    } else {
      setWithoutPic(withoutPic.filter((r) => r.email !== email));
    }
  };

  const modeLabel = (mode) => {
    if (mode === "gmail") return "Gmail assisted";
    if (mode === "public") return "Public only";
    if (mode === "contacts_only") return "Contacts only";
    return "All sources";
  };

  const clearAll = () => {
    setEmailInput("");
    setResults(null);
    setWithPic([]);
    setWithoutPic([]);
    setProgress(0);
    setOriginalRows([]);
    setOriginalColumns([]);
    setEmailColumn(null);
    setUploadedFilename(null);
  };

  return (
    <div className="space-y-6" data-testid="email-checker-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Email Profile Checker</h1>
          <p className="text-zinc-400">
            Check which emails have profile pictures — connect Google and use
            Gmail mode for results closest to Gmail compose.
          </p>
        </div>
        {(withPic.length > 0 || withoutPic.length > 0) && (
          <div className="flex gap-2">
            <Button
              onClick={downloadExcel}
              className="bg-green-600 hover:bg-green-700"
              data-testid="download-excel-btn"
            >
              <FileSpreadsheet className="w-4 h-4 mr-2" />
              Download Excel
            </Button>
            <Button
              variant="outline"
              onClick={clearAll}
              className="border-zinc-700 text-zinc-300"
              data-testid="clear-all-btn"
            >
              <Trash2 className="w-4 h-4 mr-2" />
              Clear All
            </Button>
          </div>
        )}
      </div>

      {/* Google Connection Card */}
      <Card
        className={`border ${
          googleConnected
            ? "bg-green-900/20 border-green-700"
            : "bg-yellow-900/20 border-yellow-700"
        }`}
        data-testid="google-connection-card"
      >
        <CardContent className="py-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              {googleConnected ? (
                <CheckCircle className="w-6 h-6 text-green-500" />
              ) : (
                <AlertCircle className="w-6 h-6 text-yellow-500" />
              )}
              <div>
                <p className="text-white font-medium">
                  {checkingGoogle
                    ? "Checking Google status…"
                    : googleConnected
                    ? `Google Connected${googleEmail ? ` — ${googleEmail}` : ""}`
                    : "Connect Google (Gmail Login)"}
                </p>
                <p className="text-zinc-400 text-sm">
                  {googleConnected
                    ? "Gmail mode uses Contacts + Other Contacts via People API — much closer to Gmail compose than public lookups alone."
                    : "Sign in with Google to unlock Gmail-assisted mode. Without login, only public avatars (Gravatar/Unavatar) are checked."}
                </p>
              </div>
            </div>

            <div className="flex gap-2 flex-wrap">
              {!googleConnected && !checkingGoogle && (
                <Button
                  onClick={connectGoogle}
                  className="bg-blue-600 hover:bg-blue-700"
                  data-testid="connect-google-btn"
                >
                  <Link2 className="w-4 h-4 mr-2" />
                  Connect Google
                </Button>
              )}
              {googleConnected && (
                <>
                  <Badge className="bg-green-600 self-center">Connected</Badge>
                  <Button
                    variant="outline"
                    onClick={switchGoogleAccount}
                    disabled={disconnecting}
                    className="border-zinc-600 text-zinc-200 hover:bg-zinc-800"
                    data-testid="switch-google-btn"
                    title="Disconnect and sign in with a different Google account"
                  >
                    <UserCog className="w-4 h-4 mr-2" />
                    Switch Account
                  </Button>
                  <Button
                    variant="outline"
                    onClick={disconnectGoogle}
                    disabled={disconnecting}
                    className="border-red-700 text-red-300 hover:bg-red-900/30"
                    data-testid="disconnect-google-btn"
                  >
                    <LogOut className="w-4 h-4 mr-2" />
                    {disconnecting ? "Disconnecting…" : "Disconnect"}
                  </Button>
                </>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Mode Selector */}
      <Card className="bg-zinc-900 border-zinc-800">
        <CardContent className="py-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <p className="text-white font-medium">Check Mode</p>
              <p className="text-zinc-400 text-sm">
                Choose how strictly to look up profile pictures.
              </p>
            </div>
            <div className="flex gap-2 flex-wrap" data-testid="mode-selector">
              <Button
                variant={checkMode === "gmail" ? "default" : "outline"}
                onClick={() => setCheckMode("gmail")}
                className={
                  checkMode === "gmail"
                    ? "bg-blue-600 hover:bg-blue-700"
                    : "border-zinc-700 text-zinc-300"
                }
                data-testid="mode-gmail-btn"
                title="Recommended: Google People API (Contacts + Other Contacts) + public fallback"
              >
                Gmail assisted (Recommended)
              </Button>
              <Button
                variant={checkMode === "public" ? "default" : "outline"}
                onClick={() => setCheckMode("public")}
                className={
                  checkMode === "public"
                    ? "bg-blue-600 hover:bg-blue-700"
                    : "border-zinc-700 text-zinc-300"
                }
                data-testid="mode-public-btn"
                title="Gravatar, Unavatar, Libravatar only — no Google login needed"
              >
                Public sources only
              </Button>
              <Button
                variant={checkMode === "contacts_only" ? "default" : "outline"}
                onClick={() => setCheckMode("contacts_only")}
                disabled={!googleConnected}
                className={
                  checkMode === "contacts_only"
                    ? "bg-blue-600 hover:bg-blue-700"
                    : "border-zinc-700 text-zinc-300"
                }
                data-testid="mode-contacts-btn"
                title={
                  googleConnected
                    ? "Strict: only return a match if the email is in your Google Contacts"
                    : "Connect Google to enable"
                }
              >
                Only my Google Contacts
              </Button>
              <Button
                variant={checkMode === "all" ? "default" : "outline"}
                onClick={() => setCheckMode("all")}
                className={
                  checkMode === "all"
                    ? "bg-blue-600 hover:bg-blue-700"
                    : "border-zinc-700 text-zinc-300"
                }
                data-testid="mode-all-btn"
                title="Legacy: Google (if connected) + all public lookups"
              >
                All sources
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Input Section */}
      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-white flex items-center gap-2">
            <Upload className="w-5 h-5 text-blue-500" />
            Upload Emails
          </CardTitle>
          <CardDescription>
            Upload an Excel file (.xlsx, .xls) or CSV, or paste emails directly.
            When you upload a file, the original columns &amp; rows are kept in
            the exported result.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* File Upload */}
          <div className="flex gap-4 flex-wrap items-center">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileUpload}
              accept=".xlsx,.xls,.csv,.txt"
              className="hidden"
              id="file-upload"
            />
            <Button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="bg-purple-600 hover:bg-purple-700"
              data-testid="upload-file-btn"
            >
              {uploading ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  Uploading...
                </>
              ) : (
                <>
                  <FileSpreadsheet className="w-4 h-4 mr-2" />
                  Upload Excel/CSV File
                </>
              )}
            </Button>
            <div className="flex items-center gap-2 text-zinc-500 text-sm">
              <File className="w-4 h-4" />
              Supported: .xlsx, .xls, .csv, .txt
            </div>
            {uploadedFilename && (
              <Badge className="bg-zinc-700">
                {uploadedFilename}
                {emailColumn ? ` · email column: ${emailColumn}` : ""}
                {originalRows.length ? ` · ${originalRows.length} rows` : ""}
              </Badge>
            )}
          </div>

          {/* Email Textarea */}
          <Textarea
            value={emailInput}
            onChange={(e) => setEmailInput(e.target.value)}
            placeholder="Or paste emails here (one per line, or comma separated)&#10;&#10;example1@gmail.com&#10;example2@gmail.com&#10;example3@gmail.com"
            className="bg-zinc-800 border-zinc-700 text-white h-40 font-mono text-sm"
            data-testid="email-input"
          />

          <div className="flex items-center justify-between">
            <span className="text-zinc-400 text-sm">
              {
                emailInput
                  .split(/[\n,;]+/)
                  .filter((e) => e.trim() && e.includes("@")).length
              }{" "}
              emails detected
            </span>
            <Button
              onClick={checkEmails}
              disabled={checking || emailInput.trim() === ""}
              className="bg-blue-600 hover:bg-blue-700"
              data-testid="check-btn"
            >
              {checking ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  Checking... {progress}%
                </>
              ) : (
                <>
                  <UserCheck className="w-4 h-4 mr-2" />
                  Check Profile Pictures
                </>
              )}
            </Button>
          </div>

          {checking && <Progress value={progress} className="h-2" />}
        </CardContent>
      </Card>

      {/* Results Summary */}
      {results && (
        <div className="grid grid-cols-3 gap-4">
          <Card className="bg-zinc-900 border-zinc-800">
            <CardContent className="pt-6">
              <div className="text-center">
                <div className="text-3xl font-bold text-white">{results.total}</div>
                <div className="text-zinc-400 text-sm">Total Checked</div>
                <div className="flex justify-center gap-2 mt-2">
                  {results.used_google_api && (
                    <Badge className="bg-blue-600 text-xs">Google API</Badge>
                  )}
                  {results.check_mode && (
                    <Badge className="bg-zinc-700 text-xs">
                      {modeLabel(results.check_mode)}
                    </Badge>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
          <Card className="bg-green-900/30 border-green-700">
            <CardContent className="pt-6">
              <div className="text-center">
                <div className="text-3xl font-bold text-green-400">
                  {results.with_pic}
                </div>
                <div className="text-green-300 text-sm flex items-center justify-center gap-1">
                  <Image className="w-4 h-4" />
                  Has Profile Pic
                </div>
              </div>
            </CardContent>
          </Card>
          <Card className="bg-red-900/30 border-red-700">
            <CardContent className="pt-6">
              <div className="text-center">
                <div className="text-3xl font-bold text-red-400">
                  {results.without_pic}
                </div>
                <div className="text-red-300 text-sm flex items-center justify-center gap-1">
                  <ImageOff className="w-4 h-4" />
                  No Profile Pic
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Results Lists */}
      {(withPic.length > 0 || withoutPic.length > 0) && (
        <div className="grid grid-cols-2 gap-6">
          {/* With Profile Pic */}
          <Card className="bg-zinc-900 border-zinc-800">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-green-400 flex items-center gap-2">
                  <Image className="w-5 h-5" />
                  Has Profile Picture ({withPic.length})
                </CardTitle>
                {withPic.length > 0 && (
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => copyEmails(withPic, "with pic")}
                      className="text-zinc-400 hover:text-white"
                      title="Copy emails"
                    >
                      <Copy className="w-4 h-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => downloadCSV(withPic, "emails_with_pic.csv")}
                      className="text-zinc-400 hover:text-white"
                      title="Download CSV"
                    >
                      <Download className="w-4 h-4" />
                    </Button>
                  </div>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {withPic.length === 0 ? (
                  <p className="text-zinc-500 text-center py-8">No results yet</p>
                ) : (
                  withPic.map((result, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-3 p-2 bg-zinc-800 rounded-lg hover:bg-zinc-700"
                    >
                      <img
                        src={result.pic_url}
                        alt=""
                        className="w-10 h-10 rounded-full object-cover border-2 border-green-500"
                        onError={(e) =>
                          (e.target.src = "https://via.placeholder.com/40")
                        }
                      />
                      <span className="text-white flex-1 truncate text-sm">
                        {result.email}
                      </span>
                      {result.method && (
                        <Badge className="bg-zinc-700 text-xs hidden sm:inline">
                          {result.method}
                        </Badge>
                      )}
                      <Badge className="bg-green-600 text-xs">Has Pic</Badge>
                      <button
                        onClick={() => removeEmail(result.email, true)}
                        className="text-zinc-500 hover:text-red-500 text-lg"
                      >
                        ×
                      </button>
                    </div>
                  ))
                )}
              </div>
            </CardContent>
          </Card>

          {/* Without Profile Pic */}
          <Card className="bg-zinc-900 border-zinc-800">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-red-400 flex items-center gap-2">
                  <ImageOff className="w-5 h-5" />
                  No Profile Picture ({withoutPic.length})
                </CardTitle>
                {withoutPic.length > 0 && (
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => copyEmails(withoutPic, "without pic")}
                      className="text-zinc-400 hover:text-white"
                      title="Copy emails"
                    >
                      <Copy className="w-4 h-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        downloadCSV(withoutPic, "emails_without_pic.csv")
                      }
                      className="text-zinc-400 hover:text-white"
                      title="Download CSV"
                    >
                      <Download className="w-4 h-4" />
                    </Button>
                  </div>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {withoutPic.length === 0 ? (
                  <p className="text-zinc-500 text-center py-8">No results yet</p>
                ) : (
                  withoutPic.map((result, i) => (
                    <div
                      key={i}
                      className="flex flex-col gap-1 p-2 bg-zinc-800 rounded-lg hover:bg-zinc-700"
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-zinc-700 flex items-center justify-center border-2 border-red-500 shrink-0">
                          <UserX className="w-5 h-5 text-zinc-500" />
                        </div>
                        <span className="text-white flex-1 truncate text-sm">
                          {result.email}
                        </span>
                        <Badge className="bg-red-600 text-xs shrink-0">No Pic</Badge>
                        <button
                          onClick={() => removeEmail(result.email, false)}
                          className="text-zinc-500 hover:text-red-500 text-lg"
                        >
                          ×
                        </button>
                      </div>
                      {result.note && (
                        <p className="text-zinc-500 text-xs pl-[52px] leading-snug">
                          {result.note}
                        </p>
                      )}
                    </div>
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Setup Instructions */}
      {!googleConnected && !results && (
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="pt-6">
            <h3 className="text-white font-medium mb-3">
              Setup Google Connection (For Best Results):
            </h3>
            <ol className="text-zinc-400 text-sm space-y-2 list-decimal list-inside">
              <li>
                Go to{" "}
                <a
                  href="https://console.cloud.google.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-400 underline"
                >
                  Google Cloud Console
                </a>
              </li>
              <li>Create a new project or select an existing one</li>
              <li>
                Go to "APIs &amp; Services" → "Library" → Enable "People API"
              </li>
              <li>
                Go to "APIs &amp; Services" → "Credentials" → Create "OAuth
                client ID"
              </li>
              <li>Choose "Web application" and add the redirect URI</li>
              <li>
                Add these environment variables to your backend:
                <pre className="bg-zinc-800 p-2 rounded mt-2 text-xs">
{`GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://your-domain/api/google/callback`}
                </pre>
              </li>
              <li>Restart the backend and click "Connect Google" above</li>
            </ol>
            <p className="text-zinc-500 text-xs mt-4">
              Gmail mode uses Google People API (Contacts + Other Contacts you've
              emailed). Google does not expose the same private identity graph
              Gmail compose uses for every cold email — some photos visible in
              Gmail may still show as "No Pic" here. Re-connect Google after
              deploy if you previously connected (tokens are now saved per user).
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
