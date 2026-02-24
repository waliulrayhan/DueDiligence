'use client';

import { useState, useEffect, useRef } from 'react';
import { useMutation } from '@tanstack/react-query';
import { updateAnswer, generateSingle, extractErrorMessage } from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────

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

export interface AnswerResponse {
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

export interface QuestionResponse {
  id: string;
  section_name: string | null;
  question_text: string;
  question_order: number | null;
  question_number: number | null;
  answer: AnswerResponse | null;
}

interface QuestionReviewDrawerProps {
  question: QuestionResponse | null;
  answer: AnswerResponse | null;
  projectId: string;
  onClose: () => void;
  onUpdated: (updated: AnswerResponse) => void;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function confidenceBadgeClass(score: number): string {
  if (score >= 0.7) return 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200';
  if (score >= 0.4) return 'bg-amber-50 text-amber-700 ring-1 ring-amber-200';
  return 'bg-rose-50 text-rose-700 ring-1 ring-rose-200';
}

function confidenceBarClass(score: number): string {
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

// ─── Component ────────────────────────────────────────────────────────────────

export default function QuestionReviewDrawer({
  question,
  answer,
  projectId,
  onClose,
  onUpdated,
}: QuestionReviewDrawerProps) {
  const [citationsOpen, setCitationsOpen] = useState(false);
  const [expandedCitations, setExpandedCitations] = useState<Set<string>>(new Set());
  const [manualText, setManualText] = useState('');
  const [rejectMode, setRejectMode] = useState(false);
  const [reviewerNote, setReviewerNote] = useState('');
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; msg: string } | null>(null);
  const rejectTextareaRef = useRef<HTMLTextAreaElement>(null);

  // Sync manual text when answer changes
  useEffect(() => {
    setManualText(answer?.manual_answer_text ?? '');
    setFeedback(null);
    setRejectMode(false);
    setReviewerNote('');
    setCitationsOpen(false);
    setExpandedCitations(new Set());
  }, [answer?.id, question?.id]);

  // Auto-focus + scroll rejection textarea into view
  useEffect(() => {
    if (rejectMode && rejectTextareaRef.current) {
      setTimeout(() => {
        rejectTextareaRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        rejectTextareaRef.current?.focus();
      }, 50);
    }
  }, [rejectMode]);

  const succeed = (msg: string, updated: AnswerResponse) => {
    setFeedback({ type: 'success', msg });
    onUpdated(updated);
  };
  const fail = (msg: string) => setFeedback({ type: 'error', msg });

  // ── Mutations ──────────────────────────────────────────────────────────────

  const confirmMutation = useMutation({
    mutationFn: () => updateAnswer(answer!.id, { status: 'CONFIRMED' }),
    onSuccess: (data: AnswerResponse) => succeed('Answer confirmed.', data),
    onError: (err) => fail(`Failed to confirm: ${extractErrorMessage(err)}`),  
  });

  const rejectMutation = useMutation({
    mutationFn: () =>
      updateAnswer(answer!.id, { status: 'REJECTED', reviewer_note: reviewerNote }),
    onSuccess: (data: AnswerResponse) => {
      setRejectMode(false);
      succeed('Answer rejected.', data);
    },
    onError: (err) => fail(`Failed to reject: ${extractErrorMessage(err)}`),  
  });

  const saveManualMutation = useMutation({
    mutationFn: () =>
      updateAnswer(answer!.id, {
        status: 'MANUAL_UPDATED',
        manual_answer_text: manualText,
      }),
    onSuccess: (data: AnswerResponse) => succeed('Manual answer saved.', data),
    onError: (err) => fail(`Failed to save manual answer: ${extractErrorMessage(err)}`),  
  });

  const regenerateMutation = useMutation({
    mutationFn: () => generateSingle(projectId, question!.id),
    onSuccess: (data: AnswerResponse) => succeed('Answer regenerated.', data),
    onError: (err) => fail(`Failed to regenerate: ${extractErrorMessage(err)}`),  
  });

  if (!question) return null;

  const score = answer?.confidence_score ?? 0;
  const pct = Math.round(score * 100);
  const citations = answer?.citations ?? [];
  const hasAnswer = !!answer && answer.status !== 'PENDING';
  const isConfirmed = answer?.status === 'CONFIRMED';
  const isRejected = answer?.status === 'REJECTED';
  const isReviewed = isConfirmed || isRejected;

  return (
    <>
      {/* Overlay */}
      <div className="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-sm transition-opacity" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed right-0 top-0 z-50 h-full w-135 max-w-full bg-white shadow-2xl flex flex-col border-l border-slate-200">

        {/* ── Drawer header ─────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-white">
          <div>
            <h2 className="font-semibold text-slate-900 text-base">Question Review</h2>
            {question.section_name && (
              <p className="text-xs text-slate-400 mt-0.5">{question.section_name}</p>
            )}
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 transition-colors p-1 rounded-lg hover:bg-slate-100" aria-label="Close">
            <svg className="h-5 w-5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </button>
        </div>

        {/* ── Scrollable body ───────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">

          {/* 1. QUESTION */}
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Question</p>
            <p className="text-sm text-slate-900 leading-relaxed">{question.question_text}</p>
          </div>

          {/* 2. AI ANSWER */}
          <div className="bg-indigo-50 border border-indigo-100 rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-bold uppercase tracking-widest text-indigo-400">AI Answer</p>
              {hasAnswer && (
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${confidenceBadgeClass(score)}`}>
                  {pct}% confidence
                </span>
              )}
            </div>

            {hasAnswer && (
              <div className="flex items-center gap-2 mb-2.5">
                <div className={`h-2 w-2 rounded-full ${answer!.can_answer ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                <span className="text-xs text-slate-600">{answer!.can_answer ? 'Can Answer' : 'Cannot Answer'}</span>
                <div className="flex-1 h-1 bg-indigo-100 rounded-full overflow-hidden ml-1">
                  <div className={`h-full rounded-full ${confidenceBarClass(score)}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            )}

            {hasAnswer ? (
              <p className="text-sm text-slate-800 leading-relaxed whitespace-pre-wrap">{answer!.ai_answer_text}</p>
            ) : (
              <p className="text-sm text-indigo-400 italic">Not generated yet. Click Regenerate below.</p>
            )}
          </div>

          {/* 3. CITATIONS */}
          {citations.length > 0 && (
            <div className="border border-slate-200 rounded-xl overflow-hidden">
              <button
                onClick={() => setCitationsOpen((o) => !o)}
                className="w-full flex items-center justify-between px-4 py-3 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
              >
                <span className="text-sm font-medium text-slate-700">Citations ({citations.length})</span>
                <svg className={`h-4 w-4 text-slate-400 transition-transform ${citationsOpen ? 'rotate-180' : ''}`} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </button>

              {citationsOpen && (
                <div className="divide-y divide-slate-100">
                  {citations.map((c) => {
                    const isExcerptExpanded = expandedCitations.has(c.id);
                    const toggleExcerpt = () =>
                      setExpandedCitations((prev) => {
                        const next = new Set(prev);
                        next.has(c.id) ? next.delete(c.id) : next.add(c.id);
                        return next;
                      });
                    return (
                      <div key={c.id} className="px-4 py-3 space-y-2">
                        {/* Header row */}
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 flex-wrap min-w-0">
                            <span className="text-xs font-medium text-slate-700 truncate">
                              {c.document_id ? `Doc ${c.document_id.slice(0, 8)}…` : 'Unknown doc'}
                            </span>
                            {c.page_number != null && (
                              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">p.{c.page_number}</span>
                            )}
                          </div>
                          {c.relevance_score != null && (
                            <span className="shrink-0 text-xs font-medium text-indigo-600 tabular-nums">
                              {Math.round(c.relevance_score * 100)}% match
                            </span>
                          )}
                        </div>

                        {/* Relevance bar */}
                        {c.relevance_score != null && (
                          <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                            <div className="h-full bg-indigo-400 rounded-full" style={{ width: `${Math.round(c.relevance_score * 100)}%` }} />
                          </div>
                        )}

                        {/* Excerpt with expand toggle */}
                        {c.excerpt_text && (
                          <div>
                            <p className={`text-xs font-mono text-slate-600 bg-slate-50 rounded-lg p-2.5 leading-relaxed whitespace-pre-wrap border border-slate-100 ${
                              isExcerptExpanded ? '' : 'line-clamp-3'
                            }`}>
                              {c.excerpt_text}
                            </p>
                            <button
                              onClick={toggleExcerpt}
                              className="mt-1 text-[11px] font-medium text-indigo-500 hover:text-indigo-700 transition-colors"
                            >
                              {isExcerptExpanded ? '▲ Show less' : '▼ Show full text'}
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* 4. REVIEW STATUS BANNER */}
          {isReviewed && (
            <div className={`rounded-xl border px-4 py-3.5 flex items-start gap-3 ${
              isConfirmed
                ? 'bg-emerald-50 border-emerald-200'
                : 'bg-rose-50 border-rose-200'
            }`}>
              <div className={`shrink-0 mt-0.5 h-6 w-6 rounded-full flex items-center justify-center ${
                isConfirmed ? 'bg-emerald-500' : 'bg-rose-500'
              }`}>
                {isConfirmed ? (
                  <svg className="h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                ) : (
                  <svg className="h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className={`text-sm font-semibold ${
                  isConfirmed ? 'text-emerald-800' : 'text-rose-800'
                }`}>
                  {isConfirmed ? 'Answer Confirmed' : 'Answer Rejected'}
                </p>
                {isRejected && answer?.reviewer_note && (
                  <p className="mt-1 text-xs text-rose-700 leading-relaxed">
                    <span className="font-semibold">Reason: </span>{answer.reviewer_note}
                  </p>
                )}
                <p className={`mt-1 text-[11px] ${
                  isConfirmed ? 'text-emerald-500' : 'text-rose-400'
                }`}>
                  Regenerate to review again
                </p>
              </div>
            </div>
          )}

          {/* 5. HUMAN ANSWER */}
          {answer?.manual_answer_text && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-emerald-500 mb-2">Manual Override</p>
              <p className="text-sm text-slate-800 leading-relaxed whitespace-pre-wrap">{answer.manual_answer_text}</p>
            </div>
          )}

          {/* 5. MANUAL EDIT */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1.5 uppercase tracking-wide">Your Answer</label>
            <textarea
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
              rows={5}
              placeholder="Write or paste a manual answer here…"
              className="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none transition"
            />
            <p className="mt-1 text-xs text-slate-400 text-right">{manualText.length} chars</p>
          </div>

          {/* Reject inline note */}
          {rejectMode && (
            <div className="border-2 border-rose-300 rounded-xl p-4 space-y-3 bg-rose-50 shadow-sm">
              <div className="flex items-center gap-2">
                <div className="h-5 w-5 rounded-full bg-rose-500 flex items-center justify-center shrink-0">
                  <svg className="h-3 w-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </div>
                <label className="text-sm font-semibold text-rose-800">
                  Rejection Reason <span className="text-rose-500 font-normal text-xs">(required)</span>
                </label>
              </div>
              <textarea
                ref={rejectTextareaRef}
                value={reviewerNote}
                onChange={(e) => setReviewerNote(e.target.value)}
                rows={3}
                placeholder="Why is this answer being rejected?"
                className="w-full border-2 border-rose-200 rounded-lg px-3 py-2.5 text-sm text-slate-900 placeholder:text-rose-300 focus:outline-none focus:ring-2 focus:ring-rose-400 focus:border-rose-400 resize-none bg-white"
              />
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => { setRejectMode(false); setReviewerNote(''); }}
                  className="px-3 py-1 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  onClick={() => rejectMutation.mutate()}
                  disabled={!reviewerNote.trim() || rejectMutation.isPending}
                  className="flex items-center gap-1.5 px-3 py-1 text-xs font-medium text-white bg-rose-600 rounded-lg hover:bg-rose-700 disabled:opacity-50"
                >
                  {rejectMutation.isPending && <Spinner className="h-3 w-3 text-white" />}
                  Submit Rejection
                </button>
              </div>
            </div>
          )}

          {/* Feedback message */}
          {feedback && (
            <div className={`text-sm rounded-xl px-3 py-2.5 ${
              feedback.type === 'success'
                ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                : 'bg-rose-50 text-rose-800 border border-rose-200'
            }`}>
              {feedback.msg}
            </div>
          )}
        </div>

        {/* ── Sticky action buttons ─────────────────────────────────────── */}
        <div className="border-t border-slate-200 px-4 py-3 bg-white">
          <div className="grid grid-cols-4 gap-2">
            <button
              onClick={() => confirmMutation.mutate()}
              disabled={!answer || isReviewed || confirmMutation.isPending}
              className={`flex flex-col items-center justify-center gap-1 py-2.5 text-xs font-semibold rounded-xl border transition-colors disabled:cursor-not-allowed ${
                isConfirmed
                  ? 'bg-emerald-500 border-emerald-500 text-white opacity-80'
                  : 'text-emerald-700 bg-emerald-50 border-emerald-200 hover:bg-emerald-100 disabled:opacity-40'
              }`}
            >
              {confirmMutation.isPending ? (
                <Spinner className="h-4 w-4 text-emerald-600" />
              ) : (
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
              )}
              {isConfirmed ? 'Confirmed' : 'Confirm'}
            </button>

            <button
              onClick={() => { setRejectMode(true); setFeedback(null); }}
              disabled={!answer || isReviewed || rejectMutation.isPending}
              className={`flex flex-col items-center justify-center gap-1 py-2.5 text-xs font-semibold rounded-xl border transition-colors disabled:cursor-not-allowed ${
                isRejected
                  ? 'bg-rose-500 border-rose-500 text-white opacity-80'
                  : 'text-rose-700 bg-rose-50 border-rose-200 hover:bg-rose-100 disabled:opacity-40'
              }`}
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
              {isRejected ? 'Rejected' : 'Reject'}
            </button>

            <button
              onClick={() => saveManualMutation.mutate()}
              disabled={!answer || !manualText.trim() || saveManualMutation.isPending}
              className="flex flex-col items-center justify-center gap-1 py-2.5 text-xs font-semibold text-violet-700 bg-violet-50 border border-violet-200 rounded-xl hover:bg-violet-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {saveManualMutation.isPending ? (
                <Spinner className="h-4 w-4 text-violet-600" />
              ) : (
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                </svg>
              )}
              Save
            </button>

            <button
              onClick={() => regenerateMutation.mutate()}
              disabled={regenerateMutation.isPending}
              className="flex flex-col items-center justify-center gap-1 py-2.5 text-xs font-semibold text-indigo-700 bg-indigo-50 border border-indigo-200 rounded-xl hover:bg-indigo-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {regenerateMutation.isPending ? (
                <Spinner className="h-4 w-4 text-indigo-600" />
              ) : (
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                </svg>
              )}
              Regen
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
