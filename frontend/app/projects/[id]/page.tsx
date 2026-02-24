'use client';

import { useState, useMemo } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import AsyncStatusBanner from '@/components/AsyncStatusBanner';
import QuestionReviewDrawer from '@/components/QuestionReviewDrawer';
import { getProject, getAnswers, generateAll } from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────

type ProjectStatus = 'CREATED' | 'INDEXING' | 'READY' | 'OUTDATED' | 'ERROR';
type AnswerStatus =
  | 'PENDING'
  | 'GENERATED'
  | 'CONFIRMED'
  | 'REJECTED'
  | 'MANUAL_UPDATED'
  | 'MISSING_DATA';

interface Citation {
  id: string;
  chunk_id: string | null;
  document_id: string | null;
  page_number: number | null;
  excerpt_text: string | null;
  relevance_score: number | null;
}

interface AnswerResponse {
  id: string;
  question_id: string;
  ai_answer_text: string | null;
  manual_answer_text: string | null;
  answer_text: string | null;
  can_answer: boolean;
  confidence_score: number;
  status: AnswerStatus;
  reviewer_note: string | null;
  reviewed_at: string | null;
  citations: Citation[];
}

interface QuestionResponse {
  id: string;
  section_name: string | null;
  question_text: string;
  question_order: number | null;
  question_number: number | null;
  answer: AnswerResponse | null;
}

interface ProjectResponse {
  id: string;
  name: string;
  description: string | null;
  scope: string;
  status: ProjectStatus;
  question_count: number;
  questions: QuestionResponse[];
  created_at: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const PROJECT_STATUS_CONFIG: Record<ProjectStatus, { label: string; cls: string; dot: string }> = {
  READY:    { label: 'Ready',    cls: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',  dot: 'bg-emerald-500' },
  OUTDATED: { label: 'Outdated', cls: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',        dot: 'bg-amber-500' },
  CREATED:  { label: 'Created',  cls: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200',       dot: 'bg-slate-400' },
  INDEXING: { label: 'Indexing', cls: 'bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200',     dot: 'bg-indigo-500 animate-pulse' },
  ERROR:    { label: 'Error',    cls: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200',           dot: 'bg-rose-500' },
};

const ANSWER_STATUS_CONFIG: Record<AnswerStatus, { label: string; cls: string; dot: string }> = {
  PENDING:        { label: 'Pending',      cls: 'bg-slate-100 text-slate-500 ring-1 ring-slate-200',         dot: 'bg-slate-400' },
  GENERATED:      { label: 'Generated',   cls: 'bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200',       dot: 'bg-indigo-500' },
  CONFIRMED:      { label: 'Confirmed',   cls: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',   dot: 'bg-emerald-500' },
  REJECTED:       { label: 'Rejected',    cls: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200',             dot: 'bg-rose-500' },
  MANUAL_UPDATED: { label: 'Manual',      cls: 'bg-violet-50 text-violet-700 ring-1 ring-violet-200',       dot: 'bg-violet-500' },
  MISSING_DATA:   { label: 'Missing',     cls: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',          dot: 'bg-amber-500' },
};

function confidenceColor(score: number, hasPending: boolean): string {
  if (hasPending) return 'bg-slate-200';
  if (score >= 0.7) return 'bg-emerald-500';
  if (score >= 0.4) return 'bg-amber-400';
  return 'bg-rose-500';
}

function Spinner({ className = '' }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  );
}

// ─── Accordion Section ────────────────────────────────────────────────────────

interface SectionProps {
  sectionName: string;
  questions: QuestionResponse[];
  answerMap: Record<string, AnswerResponse>;
  projectId: string;
  onReview: (q: QuestionResponse, a: AnswerResponse | null) => void;
}

function QuestionSection({ sectionName, questions, answerMap, onReview }: SectionProps) {
  const [open, setOpen] = useState(true);

  const answeredCount = questions.filter((q) => {
    const a = answerMap[q.id] ?? q.answer;
    return a && a.status !== 'PENDING';
  }).length;

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3.5 hover:bg-slate-50 transition-colors text-left"
      >
        <div className="flex items-center gap-2.5">
          <svg
            className={`h-4 w-4 text-slate-400 transition-transform flex-shrink-0 ${open ? 'rotate-90' : ''}`}
            xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"
          >
            <path fillRule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clipRule="evenodd" />
          </svg>
          <span className="font-semibold text-slate-800 text-sm">{sectionName}</span>
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600">
            {questions.length}
          </span>
        </div>
        <span className="text-xs text-slate-400">{answeredCount}/{questions.length} answered</span>
      </button>

      {open && (
        <div className="divide-y divide-slate-100 border-t border-slate-100">
          {questions.map((q) => {
            const answer = answerMap[q.id] ?? q.answer ?? null;
            const isPending = !answer || answer.status === 'PENDING';
            const score = answer?.confidence_score ?? 0;
            const pct = Math.round(score * 100);
            const statusCfg = ANSWER_STATUS_CONFIG[answer?.status ?? 'PENDING'];

            return (
              <div key={q.id} className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition-colors">
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-slate-700 truncate" title={q.question_text}>
                    {q.question_text.length > 100 ? q.question_text.slice(0, 100) + '…' : q.question_text}
                  </p>
                </div>

                <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap flex-shrink-0 ${statusCfg.cls}`}>
                  <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${statusCfg.dot}`} />
                  {statusCfg.label}
                </span>

                <div className="flex items-center gap-1.5 flex-shrink-0 w-24">
                  <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${confidenceColor(score, isPending)}`}
                      style={{ width: isPending ? '0%' : `${pct}%` }}
                    />
                  </div>
                  <span className="text-xs text-slate-400 w-7 text-right tabular-nums">
                    {isPending ? '—' : `${pct}%`}
                  </span>
                </div>

                <button
                  onClick={() => onReview(q, answer)}
                  className="flex-shrink-0 px-2.5 py-1 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-lg hover:bg-indigo-50 transition-colors"
                >
                  Review
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ProjectPage() {
  const params = useParams();
  const projectId = params?.id as string;
  const router = useRouter();
  const queryClient = useQueryClient();

  const [generateRequestId, setGenerateRequestId] = useState<string | null>(null);
  const [drawerQuestion, setDrawerQuestion] = useState<QuestionResponse | null>(null);
  const [drawerAnswer, setDrawerAnswer] = useState<AnswerResponse | null>(null);

  const { data: project, isLoading: projectLoading, isError: projectError } = useQuery<ProjectResponse>({
    queryKey: ['project', projectId],
    queryFn: () => getProject(projectId),
    refetchInterval: 5000,
    enabled: !!projectId,
  });

  const { data: answersRaw = [] } = useQuery<AnswerResponse[]>({
    queryKey: ['answers', projectId],
    queryFn: () => getAnswers(projectId),
    refetchInterval: 5000,
    enabled: !!projectId,
  });

  // Answer map: question_id → AnswerResponse
  const answerMap = useMemo<Record<string, AnswerResponse>>(() => {
    const map: Record<string, AnswerResponse> = {};
    for (const a of answersRaw) map[a.question_id] = a;
    return map;
  }, [answersRaw]);

  // Group questions by section_name
  const sections = useMemo(() => {
    const questions = project?.questions ?? [];
    const map = new Map<string, QuestionResponse[]>();
    for (const q of questions) {
      const key = q.section_name ?? 'General';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(q);
    }
    return Array.from(map.entries());
  }, [project]);

  const generateAllMutation = useMutation({
    mutationFn: () => generateAll(projectId),
    onSuccess: (data) => {
      if (data?.request_id) setGenerateRequestId(data.request_id);
    },
  });

  const openDrawer = (q: QuestionResponse, a: AnswerResponse | null) => {
    setDrawerQuestion(q);
    setDrawerAnswer(a);
  };

  const closeDrawer = () => {
    setDrawerQuestion(null);
    setDrawerAnswer(null);
  };

  const handleDrawerUpdated = () => {
    queryClient.invalidateQueries({ queryKey: ['answers', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });
  };

  if (projectLoading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-slate-50">
        <Spinner className="h-8 w-8 text-indigo-500" />
        <p className="text-sm text-slate-400">Loading project…</p>
      </div>
    );
  }

  if (projectError || !project) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-slate-50">
        <div className="flex items-center justify-center w-14 h-14 rounded-full bg-rose-50">
          <svg className="h-7 w-7 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
        </div>
        <p className="text-sm font-medium text-slate-700">{projectError ? 'Failed to load project' : 'Project not found'}</p>
        <button onClick={() => router.push('/')} className="text-xs text-indigo-600 hover:text-indigo-700 font-medium">← Back to home</button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* ── Navbar ──────────────────────────────────────────────────────── */}
      <nav className="sticky top-0 z-40 bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between h-14">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push('/')}
              className="flex items-center gap-1.5 text-slate-500 hover:text-slate-800 transition-colors"
            >
              <svg className="h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M9.707 16.707a1 1 0 01-1.414 0l-6-6a1 1 0 010-1.414l6-6a1 1 0 011.414 1.414L5.414 9H17a1 1 0 110 2H5.414l4.293 4.293a1 1 0 010 1.414z" clipRule="evenodd" />
              </svg>
              <span className="text-sm font-medium">Back</span>
            </button>
            <span className="text-slate-300">|</span>
            <span className="text-slate-900 font-bold text-base tracking-tight">
              Due<span className="text-indigo-600">Diligence</span>
            </span>
          </div>
          <span className="text-sm text-slate-500 hidden sm:block truncate max-w-xs">{project.name}</span>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-4">
        {/* ── Banner ────────────────────────────────────────────────────── */}
        <AsyncStatusBanner
          requestId={generateRequestId}
          label="Generating answers"
          onComplete={() => {
            setGenerateRequestId(null);
            queryClient.invalidateQueries({ queryKey: ['answers', projectId] });
            queryClient.invalidateQueries({ queryKey: ['project', projectId] });
          }}
        />

        {/* ── Project header ────────────────────────────────────────────── */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2.5 flex-wrap">
                <h1 className="text-xl font-bold text-slate-900">{project.name}</h1>
                {(() => {
                  const cfg = PROJECT_STATUS_CONFIG[project.status];
                  return (
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${cfg.cls}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
                      {cfg.label}
                    </span>
                  );
                })()}
              </div>
              {project.description && (
                <p className="mt-1.5 text-sm text-slate-500">{project.description}</p>
              )}
              <div className="mt-2 flex items-center gap-3 text-xs text-slate-400">
                <span>{project.question_count} questions</span>
                <span>·</span>
                <span>Scope: {project.scope}</span>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                onClick={() => generateAllMutation.mutate()}
                disabled={generateAllMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {generateAllMutation.isPending ? (
                  <Spinner className="h-4 w-4 text-white" />
                ) : (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
                  </svg>
                )}
                {generateAllMutation.isPending ? 'Generating…' : 'Generate All'}
              </button>
              <button
                onClick={() => router.push(`/projects/${projectId}/evaluation`)}
                className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
                </svg>
                Evaluation
              </button>
            </div>
          </div>

          {project.status === 'OUTDATED' && (
            <div className="mt-4 flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
              <svg className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              <p className="text-sm text-amber-800">
                New documents have been indexed since this project was last generated.
                Click <strong>Generate All</strong> to refresh answers.
              </p>
            </div>
          )}
        </div>

        {/* ── Questions panel ───────────────────────────────────────────── */}
        <div className="space-y-3">
          {sections.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 bg-white rounded-xl border border-dashed border-slate-200 text-center">
              <div className="flex items-center justify-center w-12 h-12 rounded-full bg-slate-50 mb-3">
                <svg className="h-6 w-6 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
                </svg>
              </div>
              <p className="text-sm font-medium text-slate-600">No questions found</p>
              <p className="text-xs text-slate-400 mt-1">This project has no questions to review.</p>
            </div>
          ) : (
            sections.map(([sectionName, questions]) => (
              <QuestionSection
                key={sectionName}
                sectionName={sectionName}
                questions={questions}
                answerMap={answerMap}
                projectId={projectId}
                onReview={openDrawer}
              />
            ))
          )}
        </div>
      </main>

      {/* ── Review Drawer ─────────────────────────────────────────────── */}
      {drawerQuestion && (
        <QuestionReviewDrawer
          question={drawerQuestion}
          answer={drawerAnswer}
          projectId={projectId}
          onClose={closeDrawer}
          onUpdated={handleDrawerUpdated}
        />
      )}
    </div>
  );
}
