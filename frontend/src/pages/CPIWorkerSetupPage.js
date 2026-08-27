import { useState } from "react";
import { Copy, CheckCircle2, Smartphone, Zap, AlertCircle } from "lucide-react";
import { Button } from "../components/ui/button";
import { toast } from "sonner";

export default function CPIWorkerSetupPage() {
  const [copied, setCopied] = useState(false);

  const token = localStorage.getItem("token") || "";
  const backend = process.env.REACT_APP_BACKEND_URL || "";

  const onCopy = () => {
    navigator.clipboard.writeText(token);
    setCopied(true);
    toast.success("Token copied — paste into Krexion CPI Worker config");
    setTimeout(() => setCopied(false), 2500);
  };

  const Step = ({ n, title, children }) => (
    <div className="border rounded-lg p-5 space-y-3" data-testid={`cpi-setup-step-${n}`}>
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-full bg-primary/10 text-primary font-bold flex items-center justify-center text-sm">
          {n}
        </div>
        <h3 className="text-lg font-semibold">{title}</h3>
      </div>
      <div className="text-sm text-muted-foreground space-y-2 ml-11">
        {children}
      </div>
    </div>
  );

  const Code = ({ children }) => (
    <pre className="bg-muted p-3 rounded text-xs font-mono overflow-x-auto my-2">{children}</pre>
  );

  return (
    <div className="space-y-6 max-w-4xl" data-testid="cpi-worker-setup-page">
      <div>
        <h1 className="text-2xl font-bold">Krexion Android Setup</h1>
        <p className="text-sm text-muted-foreground">
          One Krexion worker on your PC. Krexion Android Engine installs and runs automatically —
          you never install outside apps.
        </p>
      </div>

      <div className="border rounded-lg p-5 bg-emerald-500/5 border-emerald-500/30 space-y-2">
        <div className="flex items-center gap-2 text-emerald-600 font-medium">
          <Zap className="h-4 w-4" /> Fully automatic
        </div>
        <ul className="text-sm text-muted-foreground list-disc ml-6 space-y-1">
          <li>Start Krexion CPI Worker once</li>
          <li>Open Devices → <strong>Enable Krexion Android</strong></li>
          <li>Krexion downloads &amp; starts the Android engine in the background</li>
          <li>Install APKs and browse — all branded as Krexion</li>
        </ul>
      </div>

      <div className="border rounded-lg p-5 bg-amber-500/5 border-amber-500/30 space-y-2">
        <div className="flex items-center gap-2 text-amber-500 font-medium">
          <AlertCircle className="h-4 w-4" /> What you need
        </div>
        <ul className="text-sm text-muted-foreground list-disc ml-6 space-y-1">
          <li>Windows PC with enough free disk (~2 GB first time for Krexion Android Engine)</li>
          <li>Stable internet for the first automatic download</li>
          <li>Krexion account with CPI enabled</li>
        </ul>
      </div>

      <Step n={1} title="Update Krexion on your PC">
        <Code>{`cd C:\\krexion
.\\KREXION-UPDATE.bat`}</Code>
      </Step>

      <Step n={2} title="Install Krexion CPI Worker (one time)">
        Administrator PowerShell:
        <Code>{`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\\deployment\\cpi\\KREXION-CPI-SETUP.ps1`}</Code>
      </Step>

      <Step n={3} title="Paste your Krexion token">
        <div className="flex items-center gap-2 mt-1">
          <Button onClick={onCopy} data-testid="cpi-setup-copy-jwt">
            {copied ? <CheckCircle2 className="h-4 w-4 mr-2" /> : <Copy className="h-4 w-4 mr-2" />}
            {copied ? "Copied!" : "Copy My Token"}
          </Button>
        </div>
        <Code>{`api:
  base_url: "${backend}"
  token: "(paste here)"`}</Code>
        Optional (defaults are already Krexion-automatic):
        <Code>{`android:
  auto_runtime: true
  prefer_emulator: true`}</Code>
      </Step>

      <Step n={4} title="Start worker — then Enable Krexion Android">
        <Code>{`.\\deployment\\cpi\\KREXION-CPI-WORKER-START.bat`}</Code>
        <p className="flex items-center gap-2 mt-2">
          <Smartphone className="h-4 w-4" />
          Open <a href="/cpi/devices" className="text-blue-500 underline">Krexion Android / Devices</a> and click
          {" "}Enable Krexion Android. First run may take several minutes while Krexion prepares the engine.
        </p>
      </Step>

      <Step n={5} title="Done">
        Create offers with an APK URL, start jobs, or use Browse / Install APK on the device card.
        Everything the customer sees is Krexion — no third-party product names.
      </Step>
    </div>
  );
}
