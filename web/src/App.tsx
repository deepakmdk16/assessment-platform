import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { DashboardPage } from './pages/DashboardPage'
import { AddQuestionPage } from './pages/AddQuestionPage'
import { QuestionDetailPage } from './pages/QuestionDetailPage'
import { SubmissionsPage } from './pages/SubmissionsPage'
import { SubmissionDetailPage } from './pages/SubmissionDetailPage'
import { AssessmentsListPage } from './pages/AssessmentsListPage'
import { NewAssessmentPage } from './pages/NewAssessmentPage'
import { AssessmentDetailPage } from './pages/AssessmentDetailPage'
import { CandidatePage } from './pages/CandidatePage'
import { NotFoundPage } from './pages/NotFoundPage'
import { CandidateErrorFallback, ErrorBoundary } from './components/ErrorBoundary'

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/t/:token"
        element={
          <ErrorBoundary fallback={<CandidateErrorFallback />}>
            <CandidatePage />
          </ErrorBoundary>
        }
      />

      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <AppLayout>
              <DashboardPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/questions/new"
        element={
          <ProtectedRoute>
            <AppLayout>
              <AddQuestionPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/questions/:id"
        element={
          <ProtectedRoute>
            <AppLayout>
              <QuestionDetailPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />

      <Route
        path="/assessments"
        element={
          <ProtectedRoute>
            <AppLayout>
              <AssessmentsListPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/assessments/new"
        element={
          <ProtectedRoute>
            <AppLayout>
              <NewAssessmentPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/assessments/:id"
        element={
          <ProtectedRoute>
            <AppLayout>
              <AssessmentDetailPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />

      <Route
        path="/submissions"
        element={
          <ProtectedRoute>
            <AppLayout>
              <SubmissionsPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/submissions/:id"
        element={
          <ProtectedRoute>
            <SubmissionDetailPage />
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
