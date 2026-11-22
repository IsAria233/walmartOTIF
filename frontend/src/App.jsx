import {useState} from 'react';
import {Navigate, Route, Routes, useLocation} from 'react-router-dom';
import {useAuth} from './auth/AuthContext';
import RequireAuth from './auth/RequireAuth';
import {ROLES} from './api/auth';
import Layout from './components/Layout';
import CaseQueue from './features/CaseQueue';
import CaseWorkspace from './features/CaseWorkspace';
import ManagerReview from './features/ManagerReview';
import {FineList, FineDetail} from './features/Fines';
import {ErrorState, Forbidden, Loading, NotFound} from './components/States';

export function Login() {
  const {login, user, status, notice} = useAuth();
  const location = useLocation();
  const [error, setError] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const from = location.state?.from;
  const destination = typeof from === 'string' && /^\/(cases|fines|manager-review)(\/|\?|$)/.test(from) ? from : '/cases';
  if (user) return <Navigate to={destination} replace/>;
  async function submit(event) {
    event.preventDefault(); if (status === 'authenticating') return;
    setError('');
    try { await login(username.trim(), password); setPassword(''); }
    catch (failure) { setPassword(''); setError(failure.message); }
  }
  return <main className="login-page"><section className="login-left"><div className="login-brand">◇ &nbsp; OTIF Control Center<small>OPERATIONS INTELLIGENCE</small></div><div><h1>Better decisions.<br/>Clearer evidence.</h1><p>Investigate OTIF fines, trace supporting records, review Agent findings, and make auditable human decisions.</p></div><small>INTERNAL OPERATIONS PLATFORM</small></section>
    <section className="login-right"><div className="login-card"><div className="login-logo" aria-hidden="true">◇</div><div className="eyebrow">Walmart OTIF</div><h2>Welcome back</h2><p className="subtitle">Sign in to your operations workspace.</p><p role="status">{notice}</p>
      {error && <ErrorState message={error}/>}<form onSubmit={submit} aria-label="Sign in"><fieldset disabled={status === 'authenticating'}><div className="formline"><label htmlFor="username">Username</label><input id="username" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} required maxLength={150}/></div><div className="formline"><label htmlFor="password">Password</label><input id="password" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required/></div><button className="btn primary" type="submit">{status === 'authenticating' ? 'Signing in…' : 'Sign in →'}</button></fieldset></form>
      {status === 'authenticating' && <Loading message="Verifying your identity…"/>}<p className="annotation">Use your assigned internal account. Access is determined by your verified role.</p></div></section></main>;
}
export default function App() {
  return <Routes><Route path="/login" element={<Login/>}/><Route element={<RequireAuth roles={ROLES}/>}><Route element={<Layout/>}>
    <Route index element={<Navigate to="/cases" replace/>}/><Route path="cases" element={<CaseQueue/>}/><Route path="fines" element={<FineList/>}/><Route path="fines/:fineId" element={<FineDetail/>}/><Route path="cases/:caseId" element={<CaseWorkspace/>}/><Route element={<RequireAuth roles={['compliance_manager']}/>}><Route path="manager-review" element={<ManagerReview/>}/></Route><Route path="forbidden" element={<Forbidden/>}/><Route path="*" element={<NotFound/>}/>
  </Route></Route></Routes>;
}
