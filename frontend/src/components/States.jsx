import {Link} from 'react-router-dom';
export function Loading({message = 'Loading…'}) { return <div className="state" role="status"><span className="spinner"/>{message}</div>; }
export function EmptyState({title, children}) { return <div className="state"><div className="state-icon" aria-hidden="true">◇</div><h2>{title}</h2><p>{children}</p></div>; }
export function ErrorState({message, onRetry}) { return <div className="error" role="alert"><p>{message}</p>{onRetry && <button className="btn" onClick={onRetry}>Try again</button>}</div>; }
export function NotFound() { return <section className="card state"><h1>Page not found</h1><p>This address does not match a workspace page.</p><Link className="btn" to="/cases">Back to Investigations</Link></section>; }
export function Forbidden() { return <section className="card state"><h1>Access restricted</h1><p>Your role does not have access to this page.</p><Link className="btn" to="/cases">Back to Investigations</Link></section>; }
