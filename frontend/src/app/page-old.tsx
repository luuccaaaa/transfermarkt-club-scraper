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
          <form
            onSubmit={onSubmit}
            className="flex flex-col gap-8 rounded-2xl border border-slate-200 bg-white p-8 shadow-lg ring-1 ring-black/5"
          >
            <div className="flex flex-col gap-3">
              <label htmlFor="team-ids" className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                <svg className="h-4 w-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                </svg>
                Team IDs
                <span className="text-red-500">*</span>
              </label>
              <textarea
                id="team-ids"
                value={teamInput}
                onChange={(event) => setTeamInput(event.target.value)}
                placeholder="Enter club IDs (one per line or comma-separated)&#10;Example:&#10;6251&#10;27, 40"
                className="h-40 w-full rounded-lg border border-slate-300 bg-white px-4 py-3 font-mono text-sm text-slate-800 shadow-sm transition-all focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 hover:border-slate-400"
                required
              />
              <div className="flex items-center justify-between">
                <p className="text-xs text-slate-500">
                  Paste one or more Transfermarkt club IDs
                </p>
                <p className="text-xs text-slate-400 font-mono">
                  Example: <span className="bg-slate-100 px-1.5 py-0.5 rounded">6251, 27, 40</span>
                </p>
              </div>
            </div>

            <div className="flex flex-col gap-3">
              <label htmlFor="season-id" className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                <svg className="h-4 w-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
                Season ID
                <span className="text-slate-400 text-xs font-normal">(optional)</span>
              </label>
              <input
                id="season-id"
                value={seasonId}
                onChange={(event) => setSeasonId(event.target.value)}
                placeholder="e.g. 2023, 2024"
                className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-800 shadow-sm transition-all focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 hover:border-slate-400"
              />
            </div>

            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                  <svg className="h-4 w-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2-2v10z" />
                  </svg>
                  Workbook columns
                  <span className="bg-blue-100 text-blue-800 text-xs font-medium px-2 py-0.5 rounded-full">
                    {selectedFields.length} selected
                  </span>
                </span>
                <div className="flex gap-2 text-xs">
                  <button
                    type="button"
                    className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-slate-600 hover:bg-slate-50 hover:border-slate-400 transition-colors shadow-sm"
                    onClick={selectDefault}
                  >
                    Default
                  </button>
                  <button
                    type="button"
                    className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-slate-600 hover:bg-slate-50 hover:border-slate-400 transition-colors shadow-sm"
                    onClick={selectAll}
                  >
                    All
                  </button>
                  <button
                    type="button"
                    className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-slate-600 hover:bg-slate-50 hover:border-slate-400 transition-colors shadow-sm"
                    onClick={clearFields}
                  >
                    None
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2 max-h-80 overflow-y-auto p-1">
                {fieldOptions.map((field) => {
                  const checked = selectedFields.includes(field.id);
                  const isDefault = defaultFields.includes(field.id);
                  return (
                    <label
                      key={field.id}
                      className={`flex items-center gap-3 rounded-lg border p-3 text-sm transition-all cursor-pointer hover:shadow-sm ${
                        checked 
                          ? 'border-blue-300 bg-blue-50/50 shadow-sm' 
                          : 'border-slate-200 bg-white hover:border-slate-300'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleField(field.id)}
                        className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 focus:ring-offset-0"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`truncate ${checked ? 'text-slate-900 font-medium' : 'text-slate-700'}`}>
                            {field.label}
                          </span>
                          {isDefault && (
                            <span className="bg-green-100 text-green-700 text-xs font-medium px-1.5 py-0.5 rounded-full flex-shrink-0">
                              default
                            </span>
                          )}
                        </div>
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="flex items-center gap-4 pt-2">
              <button
                type="submit"
                className="flex-1 inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-blue-700 px-6 py-3 text-sm font-semibold text-white shadow-lg transition-all hover:from-blue-700 hover:to-blue-800 hover:shadow-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:from-blue-300 disabled:to-blue-400 disabled:shadow-none"
                disabled={isSubmitting}
              >
                {isSubmitting ? (
                  <>
                    <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="m4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
                    </svg>
                    Running workflow...
                  </>
                ) : (
                  <>
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h1m4 0h1M9 16v-2a4 4 0 118 0v2M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Run workflow
                  </>
                )}
              </button>
              {selectedFields.length === 0 && !isSubmitting && (
                <p className="text-xs text-amber-600">
                  ⚠️ Select at least one column
                </p>
              )}
            </div>
          </form>

          <aside className="flex flex-col gap-6">
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-lg ring-1 ring-black/5">
              <div className="mb-6 flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                  <svg className="h-5 w-5 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                  </svg>
                  Status
                </h2>
                <div className={`rounded-full px-3 py-1.5 text-xs font-semibold flex items-center gap-1.5 ${
                  jobStatus === 'completed' ? 'bg-emerald-100 text-emerald-800' :
                  jobStatus === 'failed' ? 'bg-red-100 text-red-800' :
                  jobStatus === 'running' || isSubmitting ? 'bg-blue-100 text-blue-800' :
                  'bg-slate-100 text-slate-700'
                }`}>
                  {jobStatus === 'completed' && (
                    <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  )}
                  {jobStatus === 'failed' && (
                    <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                    </svg>
                  )}
                  {(jobStatus === 'running' || isSubmitting) && (
                    <svg className="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="m4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
                    </svg>
                  )}
                  {jobStatus}
                </div>
              </div>
              <dl className="space-y-4 text-sm">
                <div className="flex justify-between items-center p-3 bg-slate-50 rounded-lg">
                  <dt className="font-semibold text-slate-700 flex items-center gap-2">
                    <svg className="h-4 w-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    Job ID
                  </dt>
                  <dd className={`font-mono text-xs px-2 py-1 rounded ${jobId ? 'bg-white text-slate-700 border' : 'text-slate-400'}`}>
                    {jobId ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold text-slate-700 mb-3 flex items-center gap-2">
                    <svg className="h-4 w-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    Live Log
                  </dt>
                  <dd>
                    <div className="rounded-lg bg-slate-950 border shadow-inner">
                      <pre className="h-72 overflow-y-auto px-4 py-3 text-xs text-slate-100 font-mono leading-relaxed scrollbar-thin scrollbar-track-slate-800 scrollbar-thumb-slate-600">
                        {formattedLogs || (
                          <span className="text-slate-400 italic">
                            {isSubmitting ? "Starting workflow..." : "Awaiting output…"}
                          </span>
                        )}
                      </pre>
                    </div>
                  </dd>
                </div>
              </dl>
            </div>

            {result && (
              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-lg ring-1 ring-black/5">
                <div className="mb-6 flex items-center justify-between">
                  <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                    <svg className="h-5 w-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    Results
                  </h2>
                  <span className="rounded-full bg-emerald-100 px-3 py-1.5 text-xs font-semibold text-emerald-800 flex items-center gap-1">
                    <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                    Complete
                  </span>
                </div>
                <div className="space-y-6 text-sm">
                  <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg p-4 border border-blue-200">
                    <h3 className="font-semibold text-slate-800 mb-3 flex items-center gap-2">
                      <svg className="h-4 w-4 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      Main Downloads
                    </h3>
                    <ul className="space-y-2">
                      <li className="flex items-center gap-2">
                        <svg className="h-4 w-4 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <a
                          className="text-blue-700 hover:text-blue-800 font-medium hover:underline transition-colors"
                          href={downloadUrl(result.workbook)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          📊 {result.workbook.split('/').pop() || result.workbook}
                        </a>
                      </li>
                      <li className="flex items-center gap-2">
                        <svg className="h-4 w-4 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <a
                          className="text-blue-700 hover:text-blue-800 font-medium hover:underline transition-colors"
                          href={downloadUrl(result.club_ids_csv)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          📝 {result.club_ids_csv.split('/').pop() || result.club_ids_csv}
                        </a>
                      </li>
                    </ul>
                  </div>
                  
                  <div className="bg-slate-50 rounded-lg p-4 border border-slate-200">
                    <h3 className="font-semibold text-slate-800 mb-3 flex items-center gap-2">
                      <svg className="h-4 w-4 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                      </svg>
                      Team CSV Files ({result.augmented_csvs.length})
                    </h3>
                    <div className="max-h-32 overflow-y-auto space-y-1">
                      {result.augmented_csvs.map((path) => (
                        <div key={path} className="flex items-center gap-2 py-1">
                          <svg className="h-3 w-3 text-slate-400" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
                          </svg>
                          <a
                            className="text-blue-600 hover:text-blue-700 text-xs hover:underline transition-colors"
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
                  
                  <div className="bg-green-50 rounded-lg p-4 border border-green-200">
                    <h3 className="font-semibold text-slate-800 mb-3 flex items-center gap-2">
                      <svg className="h-4 w-4 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                      </svg>
                      Teams Processed ({result.teams.length})
                    </h3>
                    <div className="max-h-28 overflow-y-auto space-y-1.5">
                      {result.teams.map((team) => (
                        <div key={team.club_id} className="flex items-center gap-2 text-xs">
                          <span className="bg-white border rounded px-2 py-1 font-mono text-slate-600 text-xs">
                            {team.club_id}
                          </span>
                          <span className="text-slate-700 font-medium">
                            {team.club_name}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                  
                  <div className="bg-purple-50 rounded-lg p-4 border border-purple-200">
                    <h3 className="font-semibold text-slate-800 mb-3 flex items-center gap-2">
                      <svg className="h-4 w-4 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2-2v10z" />
                      </svg>
                      Selected Fields ({result.selected_fields?.length || 0})
                    </h3>
                    <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto">
                      {(result.selected_fields ?? []).map((field) => (
                        <span
                          key={field}
                          className="inline-block rounded-full bg-white border border-purple-200 px-2 py-1 text-xs font-medium text-purple-700"
                        >
                          {renderFieldLabel(field)}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </aside>
        </section>
      </div>
    </div>
  );
}
