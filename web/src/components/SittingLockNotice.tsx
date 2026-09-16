/** Told, not silently disabled (R2-041).
 *
 *  A tab that does not hold the sitting stops recording and stops saving. Doing
 *  that quietly would be worse than the bug it fixes: the candidate would keep
 *  typing into a tab whose work goes nowhere. Both candidate flows render this,
 *  so the sentence lives in one place and has one row in docs/CLAIMS.md.
 */
export function SittingLockNotice() {
  return (
    <div className="editor-hint blocked" role="alert">
      <span>
        <strong>This assessment is open in another tab.</strong> Carry on there — this tab has
        stopped saving, so anything you type here is lost. Close the other tab to use this one
        instead.
      </span>
    </div>
  )
}
