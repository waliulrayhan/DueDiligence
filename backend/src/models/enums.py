from enum import Enum


class ProjectStatus(str, Enum):
    CREATED = 'CREATED'       # just created, no questions yet
    INDEXING = 'INDEXING'     # questionnaire being parsed
    READY = 'READY'           # questions parsed, answers can be generated
    OUTDATED = 'OUTDATED'     # new doc indexed while scope=ALL_DOCS
    ERROR = 'ERROR'           # unrecoverable failure


class AnswerStatus(str, Enum):
    PENDING = 'PENDING'                   # question has no answer yet
    GENERATED = 'GENERATED'               # AI answer saved
    CONFIRMED = 'CONFIRMED'               # reviewer approved AI answer
    REJECTED = 'REJECTED'                 # reviewer rejected, note required
    MANUAL_UPDATED = 'MANUAL_UPDATED'     # reviewer wrote their own answer
    MISSING_DATA = 'MISSING_DATA'         # cannot be answered from docs


class RequestStatus(str, Enum):
    PENDING = 'PENDING'
    RUNNING = 'RUNNING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'


class DocumentScope(str, Enum):
    ALL_DOCS = 'ALL_DOCS'               # use all indexed documents
    SELECTED_DOCS = 'SELECTED_DOCS'     # use only specified documents


class DocumentStatus(str, Enum):
    UPLOADING = 'UPLOADING'
    INDEXING = 'INDEXING'
    READY = 'READY'
    FAILED = 'FAILED'
