'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getEvaluationReport, runEvaluation, getProject, extractErrorMessage } from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────

interface EvaluationResultRow {
  question_id: string;
  question_text: string;
  ai_answer_text: string | null;
  human_answer_text: string | null;
  overall_score: number;
  similarity_score: number;
  keyword_overlap: number;
  explanation: string | null;
}

interface EvaluationAggregates {
  avg_score: number;
  count_excellent: number;
  count_good: number;
  count_poor: number;
  total: number;
}

interface EvaluationReport {
  aggregates: EvaluationAggregates;
  results: EvaluationResultRow[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function scoreBadge(score: number): { label: string; cls: string } {
  if (score >= 0.8) return { label: 'Excellent', cls: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' };
  if (score >= 0.6) return { label: 'Good', cls: 'bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200' };
  if (score >= 0.4) return { label: 'Partial', cls: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200' };
  return { label: 'Poor', cls: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200' };
}

function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

function Spinner({ className = '' }: { className?: string }) {
  return (
    <svg className={`animate-spin h-4 w-4 ${className}`} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  );
}

// ─── Run Evaluation Modal ─────────────────────────────────────────────────────

interface ProjectQuestion {
  id: string;
  question_text: string;
}

interface RunEvalModalProps {
  projectId: string;
  questions: ProjectQuestion[];
  onClose: () => void;
  onSuccess: () => void;
}

function RunEvalModal({ projectId, questions, onClose, onSuccess }: RunEvalModalProps) {
  const [answers, setAnswers] = useState<Record<string, string>>(() =>
    Object.fromEntries(questions.map((q) => [q.id, '']))
  );
  const [submitError, setSubmitError] = useState('');

  const mutation = useMutation({
    mutationFn: (groundTruth: object[]) =>
      runEvaluation({ project_id: projectId, ground_truth: groundTruth }),
    onSuccess: () => { onSuccess(); onClose(); },
    onError: (err) => setSubmitError(`Evaluation failed: ${extractErrorMessage(err)}`),
  });

  const filled = Object.values(answers).filter((v) => v.trim()).length;

  const handleSubmit = () => {
    setSubmitError('');
    const payload = questions
      .filter((q) => answers[q.id]?.trim())
      .map((q) => ({ question_id: q.id, human_answer_text: answers[q.id].trim() }));
    if (payload.length === 0) {
      setSubmitError('Please fill in at least one answer before submitting.');
      return;
    }
    mutation.mutate(payload);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ backdropFilter: 'blur(4px)', backgroundColor: 'rgba(15,23,42,0.5)' }}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 border border-slate-200 flex flex-col max-h-[90vh]">

        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-slate-100">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Run Evaluation</h2>
              <p className="text-sm text-slate-500 mt-0.5">Enter your ground-truth answer for each question.</p>
            </div>
            <span className="text-xs font-medium bg-indigo-50 text-indigo-700 px-2.5 py-1 rounded-full border border-indigo-100">
              {filled} / {questions.length} answered
            </span>
          </div>
        </div>

        {/* Scrollable question list */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {questions.length === 0 ? (
            <p className="text-sm text-slate-400 text-center py-8">No questions found for this project.</p>
          ) : (
            questions.map((q, idx) => (
              <div key={q.id} className="rounded-xl border border-slate-200 overflow-hidden">
                <div className="bg-slate-50 px-4 py-2.5 flex items-start gap-2.5">
                  <span className="mt-0.5 shrink-0 h-5 w-5 rounded-full bg-indigo-100 text-indigo-700 text-xs font-bold flex items-center justify-center">
                    {idx + 1}
                  </span>
                  <p className="text-sm text-slate-800 leading-snug">{q.question_text}</p>
                </div>
                <div className="px-4 py-3 bg-white">
                  <textarea
                    value={answers[q.id] ?? ''}
                    onChange={(e) => {
                      setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }));
                      setSubmitError('');
                    }}
                    rows={3}
                    placeholder="Type your ground-truth answer here…"
                    className={`w-full border rounded-lg px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition ${
                      answers[q.id]?.trim() ? 'border-emerald-300 bg-emerald-50/30' : 'border-slate-200'
                    }`}
                  />
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-100 bg-slate-50/50 rounded-b-2xl">
          {submitError && (
            <p className="mb-3 text-sm text-rose-600 bg-rose-50 rounded-lg px-3 py-2 border border-rose-200">{submitError}</p>
          )}
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">Questions with empty answers will be skipped.</p>
            <div className="flex gap-3">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-100 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={filled === 0 || mutation.isPending}
                className="flex items-center gap-2 px-5 py-2 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {mutation.isPending ? (
                  <><Spinner className="h-4 w-4 text-white" /> Evaluating…</>
                ) : (
                  <>
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 3l14 9-14 9V3z" />
                    </svg>
                    Run Evaluation
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Result Card ─────────────────────────────────────────────────────────────

function ResultCard({ row, index }: { row: EvaluationResultRow; index: number }) {
  const [open, setOpen] = useState(false);
  const badge = scoreBadge(row.overall_score);

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      {/* Always-visible header — click anywhere to toggle */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-5 py-4 flex items-start gap-4 hover:bg-slate-50 transition-colors group"
      >
        {/* Number */}
        <span className="mt-0.5 shrink-0 h-6 w-6 rounded-full bg-indigo-50 text-indigo-600 text-xs font-bold flex items-center justify-center ring-1 ring-indigo-100">
          {index + 1}
        </span>

        {/* Question + meta */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-slate-800 leading-snug mb-2">{row.question_text}</p>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${badge.cls}`}>
              {badge.label}
            </span>
            <span className="text-xs text-slate-400 tabular-nums font-medium">{pct(row.overall_score)}</span>
            {/* Score bar */}
            <div className="flex-1 min-w-20 max-w-40 h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  row.overall_score >= 0.8 ? 'bg-emerald-400' :
                  row.overall_score >= 0.6 ? 'bg-indigo-400' :
                  row.overall_score >= 0.4 ? 'bg-amber-400' : 'bg-rose-400'
                }`}
                style={{ width: pct(row.overall_score) }}
              />
            </div>
          </div>
        </div>

        {/* Expand chevron — rotates when open */}
        <div className={`shrink-0 mt-0.5 h-7 w-7 rounded-lg flex items-center justify-center border transition-all ${
          open
            ? 'bg-indigo-600 border-indigo-600 text-white'
            : 'bg-slate-50 border-slate-200 text-slate-400 group-hover:border-indigo-200 group-hover:text-indigo-500'
        }`}>
          <svg
            className={`h-3.5 w-3.5 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {/* Expanded detail panel */}
      {open && (
        <div className="border-t border-slate-100 px-5 py-4 bg-slate-50/60">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            <div className="bg-indigo-50 border border-indigo-100 rounded-xl p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-indigo-400 mb-2">AI Answer</p>
              <p className="text-sm text-slate-800 leading-relaxed whitespace-pre-wrap">{row.ai_answer_text ?? '—'}</p>
            </div>
            <div className="bg-emerald-50 border border-emerald-100 rounded-xl p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-emerald-500 mb-2">Human Answer</p>
              <p className="text-sm text-slate-800 leading-relaxed whitespace-pre-wrap">{row.human_answer_text ?? '—'}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-200">
            {row.explanation ? (
              <p className="text-xs text-slate-600 flex-1 min-w-0">
                <span className="font-semibold text-slate-700">Explanation: </span>{row.explanation}
              </p>
            ) : <span />}
            <div className="flex items-center gap-4 shrink-0">
              <div className="text-center">
                <p className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Semantic</p>
                <p className="text-sm font-bold text-slate-700 tabular-nums">{pct(row.similarity_score)}</p>
              </div>
              <div className="text-center">
                <p className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Keyword</p>
                <p className="text-sm font-bold text-slate-700 tabular-nums">{pct(row.keyword_overlap)}</p>
              </div>
              <div className="text-center">
                <p className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Overall</p>
                <p className="text-sm font-bold text-slate-700 tabular-nums">{pct(row.overall_score)}</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function EvaluationPage() {
  const params = useParams();
  const projectId = params?.id as string;
  const router = useRouter();
  const queryClient = useQueryClient();

  const [modalOpen, setModalOpen] = useState(false);

  const { data: projectData } = useQuery<{ questions: ProjectQuestion[] }>({  
    queryKey: ['project', projectId],
    queryFn: () => getProject(projectId),
    enabled: !!projectId,
    staleTime: 60000,
  });
  const projectQuestions: ProjectQuestion[] = projectData?.questions ?? [];

  const { data: report, isLoading, isError: evalError } = useQuery<EvaluationReport>({
    queryKey: ['evaluation', projectId],
    queryFn: () => getEvaluationReport(projectId),
    enabled: !!projectId,
    // Evaluation is not a live-polling endpoint — only refetch on window focus
    staleTime: 60000,
  });

  const handleExportCsv = () => {
    if (!report?.results?.length) return;

    const header = ['question', 'ai_answer', 'human_answer', 'score', 'explanation'];
    const escape = (v: string | null | undefined) => {
      const s = (v ?? '').replace(/"/g, '""');
      return `"${s}"`;
    };
    const rows = report.results.map((r) => [
      escape(r.question_text),
      escape(r.ai_answer_text),
      escape(r.human_answer_text),
      escape(r.overall_score.toFixed(4)),
      escape(r.explanation),
    ]);
    const csvString = [header.join(','), ...rows.map((r) => r.join(','))].join('\n');

    const blob = new Blob([csvString], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'evaluation_report.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const agg = report?.aggregates;
  const results = report?.results ?? [];
  const hasData = results.length > 0;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* ── Navbar ──────────────────────────────────────────────────────── */}
      <nav className="sticky top-0 z-40 bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between h-14">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push(`/projects/${projectId}`)}
              className="flex items-center gap-1.5 text-slate-500 hover:text-slate-800 transition-colors"
            >
              <svg className="h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M9.707 16.707a1 1 0 01-1.414 0l-6-6a1 1 0 010-1.414l6-6a1 1 0 011.414 1.414L5.414 9H17a1 1 0 110 2H5.414l4.293 4.293a1 1 0 010 1.414z" clipRule="evenodd" />
              </svg>
              <span className="text-sm">Back</span>
            </button>
            <span className="text-slate-300 select-none">|</span>
            <span className="font-semibold text-slate-900 text-sm">Evaluation Report</span>
          </div>
          <button
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-1.5 px-4 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 3l14 9-14 9V3z" />
            </svg>
            Run Evaluation
          </button>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">

        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-24 gap-3">
            <Spinner className="h-8 w-8 text-indigo-400" />
            <p className="text-sm text-slate-400">Loading report…</p>
          </div>
        ) : evalError ? (
          <div className="flex flex-col items-center justify-center py-24 space-y-3">
            <div className="h-14 w-14 rounded-2xl bg-rose-50 border border-rose-200 flex items-center justify-center">
              <svg className="h-7 w-7 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              </svg>
            </div>
            <p className="text-sm font-medium text-slate-700">Failed to load evaluation report.</p>
            <p className="text-xs text-slate-400">Make sure the backend is running and the project ID is valid.</p>
          </div>
        ) : !hasData ? (
          <div className="flex flex-col items-center justify-center py-24 border-2 border-dashed border-slate-200 rounded-2xl space-y-3">
            <div className="h-14 w-14 rounded-2xl bg-slate-100 flex items-center justify-center">
              <svg className="h-7 w-7 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.2}
                  d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <p className="text-sm font-medium text-slate-600">No evaluation data yet.</p>
            <p className="text-xs text-slate-400">Run an evaluation to compare AI answers against human ground truth.</p>
            <button
              onClick={() => setModalOpen(true)}
              className="mt-1 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors"
            >
              Run Evaluation
            </button>
          </div>
        ) : (
          <>
            {/* ── Aggregate stats ─────────────────────────────────────────── */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4 text-center col-span-2 sm:col-span-1">
                <p className="text-2xl font-bold text-slate-900">{pct(agg?.avg_score ?? 0)}</p>
                <p className="text-xs text-slate-500 mt-1 font-medium">Avg Score</p>
              </div>
              <div className="bg-white rounded-xl border-t-4 border-t-emerald-500 border border-slate-200 shadow-sm p-4 text-center">
                <p className="text-2xl font-bold text-emerald-700">{agg?.count_excellent ?? 0}</p>
                <p className="text-xs text-emerald-600 mt-1 font-medium">Excellent</p>
              </div>
              <div className="bg-white rounded-xl border-t-4 border-t-indigo-500 border border-slate-200 shadow-sm p-4 text-center">
                <p className="text-2xl font-bold text-indigo-700">{agg?.count_good ?? 0}</p>
                <p className="text-xs text-indigo-600 mt-1 font-medium">Good</p>
              </div>
              <div className="bg-white rounded-xl border-t-4 border-t-rose-500 border border-slate-200 shadow-sm p-4 text-center">
                <p className="text-2xl font-bold text-rose-700">{agg?.count_poor ?? 0}</p>
                <p className="text-xs text-rose-600 mt-1 font-medium">Poor</p>
              </div>
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4 text-center">
                <p className="text-2xl font-bold text-slate-700">{agg?.total ?? 0}</p>
                <p className="text-xs text-slate-500 mt-1 font-medium">Total</p>
              </div>
            </div>

            {/* ── Results card list ────────────────────────────────────── */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-semibold text-slate-800">{results.length} Results</h2>
                  <span className="flex items-center gap-1 text-xs text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">
                    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                    Click a card to expand
                  </span>
                </div>
                <button
                  onClick={handleExportCsv}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors bg-white"
                >
                  <svg className="h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                  Export CSV
                </button>
              </div>

              {results.map((row, idx) => (
                <ResultCard key={row.question_id} row={row} index={idx} />
              ))}
            </div>
          </>
        )}
      </main>

      {/* ── Modal ────────────────────────────────────────────────────────── */}
      {modalOpen && (
        <RunEvalModal
          projectId={projectId}
          questions={projectQuestions}
          onClose={() => setModalOpen(false)}
          onSuccess={() => queryClient.invalidateQueries({ queryKey: ['evaluation', projectId] })}
        />
      )}
    </div>
  );
}
