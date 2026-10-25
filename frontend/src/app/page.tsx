import Link from "next/link";
import { BookScene } from "@/components/book-scene";

export default function HomePage() {
  return (
    <main className="landing-page page-enter">
      <nav className="landing-nav glass-panel">
        <Link className="brand" href="/" aria-label="Bookwise home"><span className="brand-mark">B</span><span>Bookwise</span></Link>
        <div className="landing-nav-links"><a href="#how-it-works">How it works</a><Link href="/login">Sign in</Link><Link className="button button-light" href="/login">Open my library <span aria-hidden="true">↗</span></Link></div>
      </nav>
      <section className="hero-section">
        <div className="hero-copy">
          <p className="eyebrow eyebrow-light"><span className="eyebrow-star">✳</span> Your books, understood</p>
          <h1>Ask better questions.<br /><em>Find them in the book.</em></h1>
          <p className="hero-description">A calm, private space to explore your books. Get clear answers with page references, so you can always return to the source.</p>
          <div className="hero-actions"><Link className="button button-light button-large" href="/login">Start with a book <span aria-hidden="true">→</span></Link><a className="text-link" href="#how-it-works">See how it works <span aria-hidden="true">↓</span></a></div>
          <div className="hero-proof"><span className="proof-icon">◌</span><span>Private by design</span><span className="proof-divider" /><span>Sources beside every answer</span></div>
        </div>
        <div className="hero-visual"><BookScene /><div className="visual-caption"><span className="caption-line" />From page to answer, with a path back.</div></div>
      </section>
      <section className="how-section" id="how-it-works">
        <div className="how-heading"><p className="eyebrow">A thoughtful way to read</p><h2>Your book stays at the center.</h2><p>Bookwise finds the passages that matter and keeps the source close.</p></div>
        <div className="how-grid">
          <article className="how-card"><span className="how-number">01</span><div className="how-icon icon-upload">↑</div><h3>Add your book</h3><p>Upload a PDF to your private library. Your file is tied to your account.</p></article>
          <article className="how-card"><span className="how-number">02</span><div className="how-icon icon-search">⌕</div><h3>Ask in your own words</h3><p>Ask for an explanation, a comparison, or a page that discusses an idea.</p></article>
          <article className="how-card"><span className="how-number">03</span><div className="how-icon icon-cite">↗</div><h3>Return to the source</h3><p>See the passage and page behind an answer, and check it for yourself.</p></article>
        </div>
      </section>
      <footer className="landing-footer"><Link className="brand" href="/"><span className="brand-mark">B</span><span>Bookwise</span></Link><span>Read with more clarity.</span><span>© 2026</span></footer>
    </main>
  );
}
