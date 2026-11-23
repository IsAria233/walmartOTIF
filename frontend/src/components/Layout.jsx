import {NavLink, Outlet, useLocation} from 'react-router-dom';
import {useAuth} from '../auth/AuthContext';
import {ROLES, ROLE_LABELS} from '../api/auth';
export const navigation = [
  {to: '/manager-review', label: 'Manager Review', glyph: '◇', roles: ['compliance_manager']},
  {to: '/cases', label: 'Investigations', glyph: '▤', roles: ROLES},
  {to: '/fines', label: 'Fine Records', glyph: '▦', roles: ROLES},
];
export default function Layout() {
  const {user, logout, notice} = useAuth();
  const location = useLocation();
  const label = location.pathname.startsWith('/manager-review') ? 'Manager Review' : location.pathname.startsWith('/fines') ? 'Fine Records' : location.pathname.startsWith('/cases/') ? 'Case Workspace' : 'Investigations';
  return <div className="app"><a className="skip-link" href="#content">Skip to content</a>
    <aside className="sidebar"><div className="brand"><span className="brandmark">O</span><div><strong>OTIF Control Center</strong><small>Operations Intelligence</small></div></div>
      <div className="side-section">WORKSPACE</div><nav aria-label="Workspace">{navigation.filter(item => item.roles.includes(user.role)).map(item => <NavLink key={item.to} to={item.to} className={({isActive}) => `navbtn ${isActive ? 'active' : ''}`}><span aria-hidden="true">{item.glyph}</span>{item.label}</NavLink>)}</nav>
      <div className="sidefoot">Internal operations platform</div>
    </aside><section className="main"><header className="topbar"><div className="breadcrumbs">Walmart OTIF <span aria-hidden="true"> / </span><b>{label}</b></div><div className="righttop"><span className="role">{ROLE_LABELS[user.role]}</span><span className="avatar" aria-hidden="true">{ROLE_LABELS[user.role][0]}</span><button className="btn small" onClick={() => logout()}>Sign out</button></div></header>
      <main id="content" className="content"><p className="session-status" role="status">{notice}</p><Outlet/></main>
    </section></div>;
}
