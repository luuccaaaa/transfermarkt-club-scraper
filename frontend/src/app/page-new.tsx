"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

type FieldOption = {
  id: string;
  label: string;
};

type JobResult = {
  teams: { club_id: string; club_name: string }[];
  club_ids_csv: string;
  generated_csvs: string[];
  augmented_csvs: string[];
  workbook: string;
  selected_fields: string[];
};

type StreamEvent =
  | { type: "status"; status: string; timestamp?: string }
  | { type: "log"; message: string; timestamp?: string }
  | { type: "error"; error: string; timestamp?: string }
  | { type: "result"; status: string; timestamp?: string; data: JobResult };

const parseTeamIds = (input: string): string[] => {
  return input
    .split(/[\n,]+/)
    .map((part) => part.trim())
    .filter(Boolean);
};

const downloadUrl = (path: string): string =>
  `${API_BASE}/download?path=${encodeURIComponent(path)}`;

export default function HomePage() {
  const [teamInput, setTeamInput] = useState("");
  const [seasonId, setSeasonId] = useState("");
  const [fieldOptions, setFieldOptions] = useState<FieldOption[]>([]);
  const [defaultFields, setDefaultFields] = useState<string[]>([]);
  const [selectedFields, setSelectedFields] = useState<string[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string>("Idle");
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<JobResult | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    const fetchFields = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/fields`);
        if (!response.ok) {
          throw new Error("Failed to load field definitions");
        }
        const payload = await response.json();
        const options: FieldOption[] = payload.fields ?? [];
        const defaults: string[] = payload.default ?? [];
        setFieldOptions(options);
        setDefaultFields(defaults);
        setSelectedFields(defaults);
      } catch (err) {
        console.error(err);
        setError("Unable to load workbook fields. Refresh and try again.");
      }
    };

    fetchFields();

    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  const fieldLookup = useMemo(() => {
    const map = new Map<string, string>();
    for (const field of fieldOptions) {
      map.set(field.id, field.label);
    }
    return map;
  }, [fieldOptions]);

  const resetJobState = useCallback(() => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    setJobId(null);
    setJobStatus("Starting…");
    setLogs([]);
    setResult(null);
    setError(null);
  }, []);

  const appendLog = useCallback((line: string) => {
    setLogs((prev) => [...prev, line]);
  }, []);

  const handleStreamEvent = useCallback(
    (event: StreamEvent) => {
      if (event.type === "status") {
        setJobStatus(event.status ?? "running");
      }
      if (event.type === "log") {
        const timestamp = event.timestamp
          ? new Date(event.timestamp).toLocaleTimeString()
          : new Date().toLocaleTimeString();
        appendLog(`[${timestamp}] ${event.message}`);
      }
      if (event.type === "error") {
        setJobStatus("failed");
        setError(event.error || "Workflow failed");
        eventSourceRef.current?.close();
        eventSourceRef.current = null;
        setIsSubmitting(false);
      }
      if (event.type === "result") {
        setJobStatus("completed");
        setResult(event.data);
        eventSourceRef.current?.close();
        eventSourceRef.current = null;
        setIsSubmitting(false);
      }
    },
    [appendLog]
  );

  const startStream = useCallback(
    (id: string) => {
      eventSourceRef.current?.close();
      const source = new EventSource(`${API_BASE}/api/jobs/${id}/stream`);
      eventSourceRef.current = source;
      source.onmessage = (evt) => {
        if (!evt.data) return;
        try {
          const payload = JSON.parse(evt.data) as StreamEvent;
          handleStreamEvent(payload);
        } catch (err) {
          console.error("Failed to parse stream payload", err);
        }
      };
      source.onerror = () => {
        source.close();
        eventSourceRef.current = null;
        setIsSubmitting(false);
        if (!result) {
          setError("Connection to workflow stream lost.");
        }
      };
    },
    [handleStreamEvent, result]
  );

  const onSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const clubIds = parseTeamIds(teamInput);
      if (!clubIds.length) {
        setError("Provide at least one club ID.");
        return;
      }
      resetJobState();
      setIsSubmitting(true);
      try {
        const response = await fetch(`${API_BASE}/api/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            team_ids: clubIds,
            season_id: seasonId.trim() || null,
            fields: selectedFields,
          }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({ detail: "Workflow failed" }));
          throw new Error(payload.detail || "Workflow failed");
        }
        const payload: { job_id: string } = await response.json();
        setJobId(payload.job_id);
        setJobStatus("running");
        startStream(payload.job_id);
      } catch (err) {
        console.error(err);
        setError(err instanceof Error ? err.message : "Unable to start workflow");
        setJobStatus("failed");
        setIsSubmitting(false);
      }
    },
    [teamInput, seasonId, selectedFields, resetJobState, startStream]
  );

  const toggleField = useCallback(
    (fieldId: string) => {
      setSelectedFields((prev) =>
        prev.includes(fieldId)
          ? prev.filter((id) => id !== fieldId)
          : [...prev, fieldId]
      );
    },
    []
  );

  const selectAll = useCallback(() => {
    setSelectedFields(fieldOptions.map((field) => field.id));
  }, [fieldOptions]);

  const selectDefault = useCallback(() => {
    setSelectedFields(defaultFields);
  }, [defaultFields]);

  const clearFields = useCallback(() => {
    setSelectedFields([]);
  }, []);

  const formattedLogs = useMemo(() => logs.join("\n"), [logs]);

  const renderFieldLabel = useCallback(
    (fieldId: string) => fieldLookup.get(fieldId) ?? fieldId,
    [fieldLookup]
  );

  return (
    <div className="min-h-screen bg-slate-900 text-green-400 font-mono">
      {/* Header Bar */}
      <div className="bg-slate-800 border-b border-slate-700 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 bg-red-500 rounded-full"></div>
            <div className="w-3 h-3 bg-yellow-500 rounded-full"></div>
            <div className="w-3 h-3 bg-green-500 rounded-full"></div>
          </div>
          <span className="text-slate-300 text-sm ml-4">
            transfermarkt-workflow-console
          </span>
          <div className="ml-auto flex items-center gap-4 text-xs text-slate-400">
            <span>Status: <span className={
              jobStatus === 'completed' ? 'text-green-400' :
              jobStatus === 'failed' ? 'text-red-400' :
              jobStatus === 'running' || isSubmitting ? 'text-yellow-400' :
              'text-slate-400'
            }>{jobStatus}</span></span>
            {jobId && <span>Job: <span className="text-blue-400">{jobId.slice(-8)}</span></span>}
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/20 border-l-4 border-red-500 px-6 py-3 mx-6 mt-4">
          <div className="flex items-center gap-2">
            <span className="text-red-400">ERROR:</span>
            <span className="text-red-300">{error}</span>
          </div>
        </div>
      )}

      <div className="flex h-[calc(100vh-80px)]">
        {/* Left Panel - Input */}
        <div className="w-1/2 border-r border-slate-700 flex flex-col">
          <div className="bg-slate-800 border-b border-slate-700 px-4 py-2">
            <span className="text-green-400 text-sm">INPUT_PARAMETERS</span>
          </div>
          
          <form
            onSubmit={onSubmit}
            className="flex flex-col p-6 space-y-6 flex-1 overflow-y-auto"
          >
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-green-400">$</span>
                <span className="text-slate-300 text-sm">TEAM_IDS</span>
                <span className="text-red-400">*</span>
              </div>
              <textarea
                id="team-ids"
                value={teamInput}
                onChange={(event) => setTeamInput(event.target.value)}
                placeholder="# Enter club IDs (one per line or comma-separated)&#10;# Example:&#10;6251&#10;27, 40"
                className="w-full h-32 bg-slate-800 border border-slate-600 rounded px-3 py-2 text-green-400 text-sm font-mono placeholder-slate-500 focus:border-green-400 focus:outline-none resize-none"
                required
              />
            </div>

            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-green-400">$</span>
                <span className="text-slate-300 text-sm">SEASON_ID</span>
                <span className="text-slate-500 text-xs">(optional)</span>
              </div>
              <input
                id="season-id"
                value={seasonId}
                onChange={(event) => setSeasonId(event.target.value)}
                placeholder="2024"
                className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-green-400 text-sm font-mono placeholder-slate-500 focus:border-green-400 focus:outline-none"
              />
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-green-400">$</span>
                  <span className="text-slate-300 text-sm">WORKBOOK_COLUMNS</span>
                  <span className="bg-slate-700 text-green-400 text-xs px-2 py-0.5 rounded">
                    [{selectedFields.length}]
                  </span>
                </div>
                <div className="flex gap-2 text-xs">
                  <button
                    type="button"
                    className="bg-slate-700 hover:bg-slate-600 border border-slate-600 text-slate-300 px-2 py-1 rounded text-xs font-mono transition-colors"
                    onClick={selectDefault}
                  >
                    default
                  </button>
                  <button
                    type="button"
                    className="bg-slate-700 hover:bg-slate-600 border border-slate-600 text-slate-300 px-2 py-1 rounded text-xs font-mono transition-colors"
                    onClick={selectAll}
                  >
                    all
                  </button>
                  <button
                    type="button"
                    className="bg-slate-700 hover:bg-slate-600 border border-slate-600 text-slate-300 px-2 py-1 rounded text-xs font-mono transition-colors"
                    onClick={clearFields}
                  >
                    none
                  </button>
                </div>
              </div>
              <div className="max-h-64 overflow-y-auto space-y-1 pr-2">
                {fieldOptions.map((field) => {
                  const checked = selectedFields.includes(field.id);
                  const isDefault = defaultFields.includes(field.id);
                  return (
                    <label
                      key={field.id}
                      className={`flex items-center gap-2 p-2 rounded cursor-pointer text-xs transition-colors ${
                        checked 
                          ? 'bg-slate-700/50 border border-green-400/30' 
                          : 'hover:bg-slate-800/50'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleField(field.id)}
                        className="w-3 h-3 rounded bg-slate-800 border-slate-600 text-green-400 focus:ring-green-400 focus:ring-offset-0 focus:ring-1"
                      />
                      <span className={`flex-1 font-mono ${checked ? 'text-green-400' : 'text-slate-400'}`}>
                        {field.label}
                      </span>
                      {isDefault && (
                        <span className="bg-green-400/20 text-green-400 text-xs px-1.5 py-0.5 rounded font-mono">
                          def
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="pt-4 border-t border-slate-700">
              <button
                type="submit"
                className={`w-full py-3 px-4 rounded font-mono text-sm transition-all ${
                  isSubmitting
                    ? 'bg-yellow-600 text-slate-900 cursor-not-allowed'
                    : 'bg-green-600 hover:bg-green-500 text-slate-900'
                }`}
                disabled={isSubmitting}
              >
                {isSubmitting ? (
                  <span className="flex items-center justify-center gap-2">
                    <div className="w-4 h-4 border-2 border-slate-900 border-t-transparent rounded-full animate-spin"></div>
                    EXECUTING...
                  </span>
                ) : (
                  'RUN_WORKFLOW'
                )}
              </button>
              {selectedFields.length === 0 && !isSubmitting && (
                <p className="text-yellow-400 text-xs mt-2 font-mono">
                  {"> WARNING: No columns selected"}
                </p>
              )}
            </div>
          </form>
        </div>

        {/* Right Panel - Console/Logs */}
        <div className="w-1/2 flex flex-col">
          <div className="bg-slate-800 border-b border-slate-700 px-4 py-2">
            <span className="text-green-400 text-sm">CONSOLE_OUTPUT</span>
          </div>
          
          {/* Live Log Console */}
          <div className="flex-1 bg-black p-4 overflow-hidden flex flex-col">
            <div className="flex-1 overflow-y-auto">
              <pre className="text-green-400 text-xs font-mono leading-relaxed whitespace-pre-wrap">
                {formattedLogs || (
                  <span className="text-slate-500">
                    {isSubmitting ? "> Initializing workflow..." : "> Awaiting execution..."}
                  </span>
                )}
              </pre>
            </div>
          </div>

          {/* Results Section */}
          {result && (
            <div className="border-t border-slate-700 bg-slate-800 max-h-64 overflow-y-auto">
              <div className="p-4 space-y-4">
                <div className="flex items-center gap-2">
                  <span className="text-green-400">{">"}</span>
                  <span className="text-green-400 text-sm font-mono">EXECUTION_COMPLETE</span>
                </div>
                
                <div className="space-y-3 text-xs">
                  <div className="border border-green-400/30 rounded p-3 bg-green-400/5">
                    <div className="text-green-400 font-mono mb-2">DOWNLOADS:</div>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-slate-400">📊</span>
                        <a
                          className="text-blue-400 hover:text-blue-300 underline font-mono"
                          href={downloadUrl(result.workbook)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {result.workbook.split('/').pop() || result.workbook}
                        </a>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-slate-400">📝</span>
                        <a
                          className="text-blue-400 hover:text-blue-300 underline font-mono"
                          href={downloadUrl(result.club_ids_csv)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {result.club_ids_csv.split('/').pop() || result.club_ids_csv}
                        </a>
                      </div>
                    </div>
                  </div>
                  
                  <div className="border border-slate-600 rounded p-3">
                    <div className="text-slate-300 font-mono mb-2">TEAMS: [{result.teams.length}]</div>
                    <div className="max-h-20 overflow-y-auto space-y-1">
                      {result.teams.map((team) => (
                        <div key={team.club_id} className="flex items-center gap-2">
                          <span className="text-yellow-400 font-mono">{team.club_id}</span>
                          <span className="text-slate-400 text-xs">→</span>
                          <span className="text-slate-300 text-xs">{team.club_name}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  
                  <div className="border border-slate-600 rounded p-3">
                    <div className="text-slate-300 font-mono mb-2">CSV_FILES: [{result.augmented_csvs.length}]</div>
                    <div className="max-h-16 overflow-y-auto space-y-1">
                      {result.augmented_csvs.map((path) => (
                        <div key={path}>
                          <a
                            className="text-blue-400 hover:text-blue-300 underline text-xs font-mono"
                            href={downloadUrl(path)}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {path.split('/').pop() || path}
                          </a>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
