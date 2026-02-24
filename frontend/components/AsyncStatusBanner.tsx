'use client';

import { useState, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getRequestStatus } from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────

export type TaskStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';

interface RequestStatusResponse {
  status: TaskStatus;
  error_message?: string;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAsyncTask() {
  const [requestId, setRequestId] = useState<string | null>(null);
  const [status, setStatus] = useState<TaskStatus | null>(null);

  const { data } = useQuery<RequestStatusResponse>({
    queryKey: ['async-task', requestId],
    queryFn: () => getRequestStatus(requestId!),
    enabled: !!requestId,
    refetchInterval: (query) => {
      const s = (query.state.data as RequestStatusResponse | undefined)?.status;
      return s === 'COMPLETED' || s === 'FAILED' ? false : 2000;
    },
  });

  useEffect(() => {
    if (data?.status) setStatus(data.status);
  }, [data]);

  const reset = useCallback(() => {
    setRequestId(null);
    setStatus(null);
  }, []);

  return { requestId, setRequestId, status, reset };
}

// ─── Component ────────────────────────────────────────────────────────────────

interface AsyncStatusBannerProps {
  requestId: string | null;
  onComplete?: () => void;
  label?: string;
}

export default function AsyncStatusBanner({
  requestId,
  onComplete,
  label = 'Processing',
}: AsyncStatusBannerProps) {
  const [elapsed, setElapsed] = useState(0);
  const [visible, setVisible] = useState(true);
  const [dismissed, setDismissed] = useState(false);

  const { data } = useQuery<RequestStatusResponse>({
    queryKey: ['async-task-banner', requestId],
    queryFn: () => getRequestStatus(requestId!),
    enabled: !!requestId,
    refetchInterval: (query) => {
      const s = (query.state.data as RequestStatusResponse | undefined)?.status;
      return s === 'COMPLETED' || s === 'FAILED' ? false : 2000;
    },
  });

  const status = data?.status ?? null;
  const errorMessage = data?.error_message;

  // Reset per new requestId
  useEffect(() => {
    setDismissed(false);
    setVisible(true);
    setElapsed(0);
  }, [requestId]);

  // Elapsed timer — stops when terminal status reached
  useEffect(() => {
    if (!requestId || status === 'COMPLETED' || status === 'FAILED') return;
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, [requestId, status]);

  // COMPLETED: fire callback + fade out after 3 s
  useEffect(() => {
    if (status !== 'COMPLETED') return;
    onComplete?.();
    const timer = setTimeout(() => setVisible(false), 3000);
    return () => clearTimeout(timer);
  }, [status, onComplete]);

  // Nothing to show
  if (!requestId || dismissed) return null;
  if (status === 'COMPLETED' && !visible) return null;

  const fmt = (s: number) =>
    `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

  // ── PENDING / RUNNING ──
  if (!status || status === 'PENDING' || status === 'RUNNING') {
    return (
      <div className="w-full flex items-center justify-between bg-indigo-50 border border-indigo-200 text-indigo-800 rounded-xl px-4 py-3 shadow-sm">
        <div className="flex items-center gap-2.5">
          <svg className="animate-spin h-4 w-4 text-indigo-500 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          <span className="text-sm font-medium">{label}… please wait</span>
        </div>
        <span className="text-sm font-mono tabular-nums text-indigo-500">{fmt(elapsed)}</span>
      </div>
    );
  }

  // ── COMPLETED ──
  if (status === 'COMPLETED') {
    return (
      <div className={`w-full flex items-center gap-2.5 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl px-4 py-3 shadow-sm transition-opacity duration-500 ${visible ? 'opacity-100' : 'opacity-0'}`}>
        <svg className="h-4 w-4 text-emerald-600 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
        </svg>
        <span className="text-sm font-medium">Done—{label} completed successfully.</span>
      </div>
    );
  }

  // ── FAILED ──
  if (status === 'FAILED') {
    return (
      <div className="w-full flex items-center justify-between bg-rose-50 border border-rose-200 text-rose-800 rounded-xl px-4 py-3 shadow-sm">
        <div className="flex items-center gap-2.5">
          <svg className="h-4 w-4 text-rose-500 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
          </svg>
          <span className="text-sm font-medium">Failed: {errorMessage ?? 'Unknown error'}</span>
        </div>
        <button onClick={() => setDismissed(true)} aria-label="Dismiss" className="ml-4 text-rose-400 hover:text-rose-600 flex-shrink-0">
          <svg className="h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
        </button>
      </div>
    );
  }

  return null;
}
