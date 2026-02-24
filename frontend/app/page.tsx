'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import AsyncStatusBanner from '@/components/AsyncStatusBanner';
import {
  getProjects,
  getDocuments,
  uploadDocument,
  createProject,
  extractErrorMessage,
} from '@/lib/api';

// ─── Local types ──────────────────────────────────────────────────────────────

type ProjectStatus = 'CREATED' | 'INDEXING' | 'READY' | 'OUTDATED' | 'ERROR';
type DocumentStatus = 'UPLOADING' | 'INDEXING' | 'READY' | 'FAILED';
type DocumentScope = 'ALL_DOCS' | 'SELECTED_DOCS';

interface Project {
  id: string;
  name: string;
  description: string | null;
  status: ProjectStatus;
  question_count: number;
  created_at: string;
}

interface Document {
  id: string;
  original_name: string;
  status: DocumentStatus;
  chunk_count: number;
  created_at: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

const PROJECT_STATUS_CONFIG: Record<ProjectStatus, { label: string; cls: string; dot: string }> = {
  READY:    { label: 'Ready',    cls: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',  dot: 'bg-emerald-500' },
  OUTDATED: { label: 'Outdated', cls: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',        dot: 'bg-amber-500' },
  CREATED:  { label: 'Created',  cls: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200',       dot: 'bg-slate-400' },
  INDEXING: { label: 'Indexing', cls: 'bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200',     dot: 'bg-indigo-500 animate-pulse' },
  ERROR:    { label: 'Error',    cls: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200',           dot: 'bg-rose-500' },
};

const DOC_STATUS_CONFIG: Record<DocumentStatus, { label: string; cls: string; dot: string }> = {
  READY:     { label: 'Ready',     cls: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200', dot: 'bg-emerald-500' },
  INDEXING:  { label: 'Indexing',  cls: 'bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200',   dot: 'bg-indigo-500 animate-pulse' },
  FAILED:    { label: 'Failed',    cls: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200',         dot: 'bg-rose-500' },
  UPLOADING: { label: 'Uploading', cls: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200',     dot: 'bg-slate-400' },
};

// ─── SVG icons ────────────────────────────────────────────────────────────────

function BriefcaseIcon({ className = '' }: { className?: string }) {
  return (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 00.75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 00-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0112 15.75c-2.648 0-5.195-.429-7.577-1.22a2.016 2.016 0 01-.673-.38m0 0A2.18 2.18 0 013 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 013.413-.387m7.5 0V5.25A2.25 2.25 0 0013.5 3h-3a2.25 2.25 0 00-2.25 2.25v.894m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  );
}

function FileTextIcon({ className = '' }: { className?: string }) {
  return (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  );
}

function UploadIcon({ className = '' }: { className?: string }) {
  return (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
    </svg>
  );
}

function PlusIcon({ className = '' }: { className?: string }) {
  return (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
    </svg>
  );
}

function Spinner({ className = '' }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  );
}

// ─── Upload Modal ─────────────────────────────────────────────────────────────

interface UploadModalProps {
  onClose: () => void;
  onRequestId: (id: string) => void;
}

function UploadModal({ onClose, onRequestId }: UploadModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');

  const mutation = useMutation({
    mutationFn: () => uploadDocument(file!),
    onSuccess: (data) => {
      if (data?.request_id) onRequestId(data.request_id);
      onClose();
    },
    onError: (err) => setError(`Upload failed: ${extractErrorMessage(err)}`),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ backdropFilter: 'blur(4px)', backgroundColor: 'rgba(15,23,42,0.5)' }}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 border border-slate-100">
        <div className="flex items-center gap-3 mb-6">
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-indigo-50">
            <UploadIcon className="h-5 w-5 text-indigo-600" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-slate-900">Upload Document</h2>
            <p className="text-xs text-slate-500 mt-0.5">PDF or DOCX files supported</p>
          </div>
        </div>

        <div
          className={`relative border-2 border-dashed rounded-xl p-6 text-center transition-colors ${
            file ? 'border-indigo-300 bg-indigo-50/50' : 'border-slate-200 hover:border-slate-300 bg-slate-50'
          }`}
        >
          <input
            type="file"
            accept=".pdf,.docx"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setError(''); }}
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          />
          {file ? (
            <div className="space-y-1.5">
              <FileTextIcon className="h-8 w-8 text-indigo-500 mx-auto" />
              <p className="text-sm font-medium text-slate-800 truncate px-4">{file.name}</p>
              <p className="text-xs text-slate-400">{(file.size / 1024).toFixed(1)} KB</p>
            </div>
          ) : (
            <div className="space-y-2">
              <UploadIcon className="h-8 w-8 text-slate-300 mx-auto" />
              <div>
                <p className="text-sm font-medium text-slate-700">Click or drag to upload</p>
                <p className="text-xs text-slate-400 mt-0.5">PDF or DOCX, up to 50MB</p>
              </div>
            </div>
          )}
        </div>

        {error && (
          <p className="mt-3 text-xs text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">{error}</p>
        )}

        <div className="mt-5 flex justify-end gap-2.5">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50">
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!file || mutation.isPending}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
          >
            {mutation.isPending ? <Spinner className="h-4 w-4 text-white" /> : <UploadIcon className="h-4 w-4" />}
            {mutation.isPending ? 'Uploading…' : 'Upload'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Create Project Modal ─────────────────────────────────────────────────────

interface CreateProjectModalProps {
  documents: Document[];
  onClose: () => void;
  onRequestId: (id: string) => void;
}

function CreateProjectModal({ documents, onClose, onRequestId }: CreateProjectModalProps) {
  const readyDocs = documents.filter((d) => d.status === 'READY');

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [questionnaireDocId, setQuestionnaireDocId] = useState('');
  const [scope, setScope] = useState<DocumentScope>('ALL_DOCS');
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [error, setError] = useState('');

  const toggleDoc = (id: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    );
  };

  const mutation = useMutation({
    mutationFn: () =>
      createProject({
        name,
        description,
        questionnaire_doc_id: questionnaireDocId,
        scope,
        document_ids: scope === 'SELECTED_DOCS' ? selectedDocIds : [],
      }),
    onSuccess: (data) => {
      if (data?.request_id) onRequestId(data.request_id);
      onClose();
    },
    onError: (err) => setError(`Failed to create project: ${extractErrorMessage(err)}`),
  });

  const isValid = name.trim() && questionnaireDocId;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ backdropFilter: 'blur(4px)', backgroundColor: 'rgba(15,23,42,0.5)' }}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto border border-slate-100">
        <div className="flex items-center gap-3 mb-6">
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-indigo-50">
            <BriefcaseIcon className="h-5 w-5 text-indigo-600" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-slate-900">New Project</h2>
            <p className="text-xs text-slate-500 mt-0.5">Configure your due diligence project</p>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1.5 uppercase tracking-wide">
              Project Name <span className="text-rose-500 normal-case font-normal">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Q4 2025 Due Diligence"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1.5 uppercase tracking-wide">
              Description <span className="text-slate-400 normal-case font-normal">(optional)</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Brief description of this project…"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition resize-none"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1.5 uppercase tracking-wide">
              Questionnaire <span className="text-rose-500 normal-case font-normal">*</span>
            </label>
            <select
              value={questionnaireDocId}
              onChange={(e) => setQuestionnaireDocId(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-900 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition"
            >
              <option value="">Select a questionnaire document…</option>
              {readyDocs.map((doc) => (
                <option key={doc.id} value={doc.id}>{doc.original_name}</option>
              ))}
            </select>
            {readyDocs.length === 0 && (
              <p className="mt-1.5 text-xs text-amber-600 flex items-center gap-1">
                <svg className="h-3.5 w-3.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
                No ready documents — upload and index a file first.
              </p>
            )}
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-2 uppercase tracking-wide">Document Scope</label>
            <div className="grid grid-cols-2 gap-2">
              {(['ALL_DOCS', 'SELECTED_DOCS'] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setScope(s)}
                  className={`flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border text-sm font-medium transition ${
                    scope === s
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                      : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  <div className={`h-4 w-4 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${scope === s ? 'border-indigo-500' : 'border-slate-300'}`}>
                    {scope === s && <div className="h-2 w-2 rounded-full bg-indigo-500" />}
                  </div>
                  {s === 'ALL_DOCS' ? 'All Documents' : 'Selected Only'}
                </button>
              ))}
            </div>
          </div>

          {scope === 'SELECTED_DOCS' && (
            <div className="border border-slate-200 rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-slate-50 border-b border-slate-200">
                <p className="text-xs font-medium text-slate-600">Select documents to include</p>
              </div>
              <div className="max-h-36 overflow-y-auto p-2 space-y-1">
                {readyDocs.length === 0 ? (
                  <p className="text-xs text-slate-400 py-3 text-center">No ready documents available.</p>
                ) : (
                  readyDocs.map((doc) => (
                    <label key={doc.id} className="flex items-center gap-2.5 px-2 py-1.5 rounded-lg hover:bg-slate-50 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={selectedDocIds.includes(doc.id)}
                        onChange={() => toggleDoc(doc.id)}
                        className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                      />
                      <span className="text-sm text-slate-700 truncate">{doc.original_name}</span>
                    </label>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {error && (
          <p className="mt-4 text-xs text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">{error}</p>
        )}

        <div className="mt-6 flex justify-end gap-2.5">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50">
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!isValid || mutation.isPending}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
          >
            {mutation.isPending && <Spinner className="h-4 w-4 text-white" />}
            {mutation.isPending ? 'Creating…' : 'Create Project'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function HomePage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [uploadRequestId, setUploadRequestId] = useState<string | null>(null);
  const [createRequestId, setCreateRequestId] = useState<string | null>(null);

  const { data: projects = [], isLoading: projectsLoading, isError: projectsError } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: getProjects,
    refetchInterval: 5000,
  });

  const { data: documents = [], isLoading: docsLoading, isError: docsError } = useQuery<Document[]>({
    queryKey: ['documents'],
    queryFn: getDocuments,
    refetchInterval: 5000,
  });

  return (
    <div className="min-h-screen bg-slate-50">
      {/* ── Navbar ─────────────────────────────────────────────────────────── */}
      <nav className="sticky top-0 z-40 bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between h-14">
          <div className="flex items-center gap-2.5">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-600">
              <svg className="h-[18px] w-[18px] text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 00.75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 00-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0112 15.75c-2.648 0-5.195-.429-7.577-1.22a2.016 2.016 0 01-.673-.38m0 0A2.18 2.18 0 013 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 013.413-.387m7.5 0V5.25A2.25 2.25 0 0013.5 3h-3a2.25 2.25 0 00-2.25 2.25v.894m7.5 0a48.667 48.667 0 00-7.5 0" />
              </svg>
            </div>
            <span className="text-slate-900 font-bold text-base tracking-tight">
              Due<span className="text-indigo-600">Diligence</span>
            </span>
          </div>
          <button
            onClick={() => setUploadOpen(true)}
            className="flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-lg hover:bg-indigo-50 transition-colors"
          >
            <UploadIcon className="h-4 w-4" />
            Upload Document
          </button>
        </div>
      </nav>

      {/* ── Global banners ────────────────────────────────────────────────── */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-4 space-y-2">
        <AsyncStatusBanner
          requestId={uploadRequestId}
          label="Indexing document"
          onComplete={() => {
            setUploadRequestId(null);
            queryClient.invalidateQueries({ queryKey: ['documents'] });
          }}
        />
        <AsyncStatusBanner
          requestId={createRequestId}
          label="Creating project"
          onComplete={() => {
            setCreateRequestId(null);
            queryClient.invalidateQueries({ queryKey: ['projects'] });
          }}
        />
      </div>

      {/* ── Main content ──────────────────────────────────────────────────── */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="flex flex-col lg:flex-row gap-6">

          {/* ── LEFT — Projects (60%) ───────────────────────────────────── */}
          <section className="lg:w-[60%]">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Projects</h2>
                <p className="text-xs text-slate-500 mt-0.5">{projects.length} project{projects.length !== 1 ? 's' : ''}</p>
              </div>
              <button
                onClick={() => setCreateOpen(true)}
                className="flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors shadow-sm"
              >
                <PlusIcon className="h-4 w-4" />
                New Project
              </button>
            </div>

            {projectsLoading ? (
              <div className="flex flex-col items-center justify-center py-16 gap-3">
                <Spinner className="h-7 w-7 text-indigo-500" />
                <p className="text-sm text-slate-400">Loading projects…</p>
              </div>
            ) : projectsError ? (
              <div className="flex flex-col items-center justify-center py-20 bg-white rounded-2xl border border-slate-200">
                <div className="flex items-center justify-center w-12 h-12 rounded-full bg-rose-50 mb-3">
                  <svg className="h-6 w-6 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                  </svg>
                </div>
                <p className="text-sm font-medium text-slate-700">Could not connect to backend</p>
                <p className="text-xs text-slate-400 mt-1 text-center px-6">Make sure the API server is running at {process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api'}</p>
              </div>
            ) : projects.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 bg-white rounded-2xl border border-dashed border-slate-200">
                <div className="flex items-center justify-center w-12 h-12 rounded-full bg-slate-50 mb-3">
                  <BriefcaseIcon className="h-6 w-6 text-slate-300" />
                </div>
                <p className="text-sm font-medium text-slate-600">No projects yet</p>
                <p className="text-xs text-slate-400 mt-1">Create your first project to get started.</p>
                <button
                  onClick={() => setCreateOpen(true)}
                  className="mt-4 flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-lg hover:bg-indigo-50"
                >
                  <PlusIcon className="h-4 w-4" />
                  Create Project
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {projects.map((project) => {
                  const cfg = PROJECT_STATUS_CONFIG[project.status];
                  return (
                    <div
                      key={project.id}
                      onClick={() => router.push(`/projects/${project.id}`)}
                      className="group bg-white rounded-xl border border-slate-200 shadow-sm p-4 flex flex-col gap-3 hover:shadow-md hover:border-slate-300 transition-all cursor-pointer"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="font-semibold text-slate-900 text-sm leading-snug flex-1">{project.name}</p>
                        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap flex-shrink-0 ${cfg.cls}`}>
                          <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${cfg.dot}`} />
                          {cfg.label}
                        </span>
                      </div>
                      {project.description && (
                        <p className="text-xs text-slate-500 line-clamp-2 -mt-1">{project.description}</p>
                      )}
                      <div className="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-slate-100 mt-auto">
                        <span>{project.question_count} questions</span>
                        <span>{formatDate(project.created_at)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* ── RIGHT — Documents (40%) ──────────────────────────────────── */}
          <section className="lg:w-[40%]">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Documents</h2>
                <p className="text-xs text-slate-500 mt-0.5">{documents.length} file{documents.length !== 1 ? 's' : ''}</p>
              </div>
              <button
                onClick={() => setUploadOpen(true)}
                className="flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors shadow-sm"
              >
                <UploadIcon className="h-4 w-4" />
                Upload
              </button>
            </div>

            {docsLoading ? (
              <div className="flex flex-col items-center justify-center py-16 gap-3">
                <Spinner className="h-7 w-7 text-indigo-500" />
                <p className="text-sm text-slate-400">Loading documents…</p>
              </div>
            ) : docsError ? (
              <div className="flex flex-col items-center justify-center py-16 bg-white rounded-2xl border border-slate-200">
                <p className="text-sm text-rose-500">Could not load documents.</p>
              </div>
            ) : documents.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 bg-white rounded-2xl border border-dashed border-slate-200">
                <div className="flex items-center justify-center w-12 h-12 rounded-full bg-slate-50 mb-3">
                  <FileTextIcon className="h-6 w-6 text-slate-300" />
                </div>
                <p className="text-sm font-medium text-slate-600">No documents uploaded</p>
                <p className="text-xs text-slate-400 mt-1">Upload a PDF or DOCX to get started.</p>
                <button
                  onClick={() => setUploadOpen(true)}
                  className="mt-4 flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-lg hover:bg-indigo-50"
                >
                  <UploadIcon className="h-4 w-4" />
                  Upload Document
                </button>
              </div>
            ) : (
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm divide-y divide-slate-100 overflow-hidden">
                {documents.map((doc) => {
                  const cfg = DOC_STATUS_CONFIG[doc.status];
                  return (
                    <div key={doc.id} className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition-colors">
                      <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-slate-100 flex-shrink-0">
                        <FileTextIcon className="h-4 w-4 text-slate-500" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-800 truncate">{doc.original_name}</p>
                        <p className="text-xs text-slate-400 mt-0.5">{doc.chunk_count} chunks · {formatDate(doc.created_at)}</p>
                      </div>
                      <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap flex-shrink-0 ${cfg.cls}`}>
                        <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${cfg.dot}`} />
                        {cfg.label}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      </main>

      {/* ── Modals ────────────────────────────────────────────────────────── */}
      {uploadOpen && (
        <UploadModal
          onClose={() => setUploadOpen(false)}
          onRequestId={(id) => setUploadRequestId(id)}
        />
      )}
      {createOpen && (
        <CreateProjectModal
          documents={documents}
          onClose={() => setCreateOpen(false)}
          onRequestId={(id) => setCreateRequestId(id)}
        />
      )}
    </div>
  );
}
