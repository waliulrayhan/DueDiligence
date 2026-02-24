import axios from 'axios';

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api',
  timeout: 15000, // 15 s — prevents requests from hanging forever when backend is unreachable
});

api.interceptors.response.use(
  (response) => {
    console.debug(
      `[API] ${response.config.method?.toUpperCase()} ${response.config.url} → ${response.status}`,
    );
    return response;
  },
  (error) => {
    if (error.code === 'ECONNABORTED') {
      console.error('[API] Request timed out:', error.config?.url);
    } else if (error.response) {
      // Server responded with a non-2xx status
      console.error(
        `[API] ${error.config?.method?.toUpperCase()} ${error.config?.url} → ${error.response.status}`,
        '\nResponse body:', error.response.data,
      );
    } else if (error.request) {
      // Request was made but no response received (network down, CORS preflight blocked, etc.)
      console.error(
        `[API] No response for ${error.config?.method?.toUpperCase()} ${error.config?.url}`,
        '\nPossible causes: backend not running, CORS rejection, or network error.',
        '\nRequest details:', error.request,
      );
    } else {
      console.error('[API] Unexpected error:', error.message);
    }
    return Promise.reject(error);
  }
);

/** Extract a human-readable error message from an axios error. */
export function extractErrorMessage(error: unknown): string {
  if (
    error &&
    typeof error === 'object' &&
    'response' in error &&
    error.response &&
    typeof error.response === 'object' &&
    'data' in error.response
  ) {
    const data = (error.response as { data: unknown }).data;
    if (typeof data === 'string') return data;
    if (data && typeof data === 'object' && 'detail' in data) {
      const d = (data as { detail: unknown }).detail;
      return typeof d === 'string' ? d : JSON.stringify(d);
    }
    return JSON.stringify(data);
  }
  if (error instanceof Error) return error.message;
  return 'Unknown error';
}

// Documents
export const uploadDocument = (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  // Do NOT set Content-Type manually — axios must auto-set it with the
  // multipart boundary when it receives a FormData payload. Manually setting
  // 'multipart/form-data' without the boundary causes the server to fail
  // parsing the body (even though it returns 202 for the request itself).
  return api.post('/documents/', formData).then((res) => res.data);
};

export const getDocuments = () =>
  api.get('/documents/').then((res) => res.data);

// Projects
export const createProject = (data: object) =>
  api.post('/projects/create', data).then((res) => res.data);

export const getProjects = () =>
  api.get('/projects/').then((res) => res.data);

export const getProject = (id: string) =>
  api.get(`/projects/${id}`).then((res) => res.data);

// Answers
export const generateSingle = (projectId: string, questionId: string) =>
  api.post('/answers/generate-single', {
    project_id: projectId,
    question_id: questionId,
  }, { timeout: 120_000 }).then((res) => res.data); // LLM calls can take up to ~60 s

export const generateAll = (projectId: string) =>
  api.post('/answers/generate-all', { project_id: projectId }).then((res) => res.data);

export const updateAnswer = (answerId: string, data: object) =>
  api.post('/answers/update', { answer_id: answerId, ...data }).then((res) => res.data);

export const getAnswers = (projectId: string) =>
  api.get(`/answers/${projectId}`).then((res) => res.data);

// Requests
export const getRequestStatus = (requestId: string) =>
  api.get(`/requests/${requestId}`).then((res) => res.data);

// Evaluation
export const runEvaluation = (data: object) =>
  api.post('/evaluation', data).then((res) => res.data);

export const getEvaluationReport = (projectId: string) =>
  api.get(`/evaluation/${projectId}`).then((res) => res.data);

export default api;
