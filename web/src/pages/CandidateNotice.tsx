export function CandidateNotice({ title, body }: { title: string; body: string }) {
  return (
    <div className="auth">
      <div className="auth-card notice-card">
        <h1>{title}</h1>
        <p className="muted">{body}</p>
      </div>
    </div>
  )
}
