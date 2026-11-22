import {Navigate, Outlet, useLocation} from 'react-router-dom';
import {useAuth} from './AuthContext';
import {Loading} from '../components/States';
export default function RequireAuth({roles}) {
  const {status, user} = useAuth();
  const location = useLocation();
  if (status === 'authenticating') return <Loading message="Verifying your identity…"/>;
  if (!user) return <Navigate to="/login" state={{from: location.pathname + location.search}} replace/>;
  if (roles && !roles.includes(user.role)) return <Navigate to="/forbidden" replace/>;
  return <Outlet/>;
}
