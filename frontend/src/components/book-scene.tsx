export function BookScene() {
  return (
    <div className="book-scene" aria-hidden="true">
      <div className="scene-orb scene-orb-one" />
      <div className="scene-orb scene-orb-two" />
      <div className="scene-glass-card">
        <span className="scene-card-line scene-card-line-strong" />
        <span className="scene-card-line" />
        <span className="scene-card-line scene-card-line-short" />
      </div>
      <div className="scene-book scene-book-back" />
      <div className="scene-book scene-book-front"><span /><span /><span /><span /></div>
      <div className="scene-page scene-page-one" />
      <div className="scene-page scene-page-two" />
      <div className="scene-citation-dot citation-dot-one" />
      <div className="scene-citation-dot citation-dot-two" />
      <div className="scene-citation-dot citation-dot-three" />
      <div className="scene-connection" />
    </div>
  );
}
