import {act, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {createMemoryRouter, RouterProvider, MemoryRouter, Route, Routes} from 'react-router-dom';
import {afterEach, describe, expect, it, vi} from 'vitest';
import App, {Login} from '../App';
import {AuthProvider} from '../auth/AuthContext';
import RequireAuth from '../auth/RequireAuth';
import {createApiClient} from '../api/client';
import {tokenExpiry, validateIdentity} from '../api/auth';
import {EmptyState, ErrorState, Loading} from '../components/States';

const id = 'b8fe47fd-7f89-49bf-8fa9-e4c7da8c72f4';
const jwt = (exp = Math.floor(Date.now()/1000)+1800) => `header.${btoa(JSON.stringify({exp}))}.signature`;
const json = (body, status=200) => new Response(JSON.stringify(body), {status, headers:{'Content-Type':'application/json'}});
function mockLogin(role='dispute_associate', identity={user_id:id, role}) {
  const token=jwt();
  const fetcher=vi.fn().mockResolvedValueOnce(json({access_token:token,token_type:'bearer'})).mockResolvedValueOnce(json(identity));
  vi.stubGlobal('fetch',fetcher);return {fetcher,token};
}
function mount(path='/cases') { const router = createMemoryRouter([{path:'*',element:<AuthProvider><App/></AuthProvider>}],{initialEntries:[path]}); render(<RouterProvider router={router}/>); return router; }
async function signIn(options) {
  const user=userEvent.setup(options);
  await user.type(screen.getByLabelText('Username'),'assigned_user');
  await user.type(screen.getByLabelText('Password'),'entered-password');
  await user.click(screen.getByRole('button',{name:'Sign in →'}));return user;
}
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});

describe('application and authentication',()=>{
  it('redirects a protected deep link to login and returns after verified login',async()=>{
    const {fetcher,token}=mockLogin();mount('/cases/example');
    expect(screen.getByRole('heading',{name:'Welcome back'})).toBeInTheDocument();
    await signIn();
    expect(await screen.findByRole('heading',{level:1,name:'Case Workspace'})).toBeInTheDocument();
    expect(fetcher.mock.calls[0][0]).toBe('/api/auth/login');
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBeUndefined();
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({username:'assigned_user',password:'entered-password'});
    expect(fetcher.mock.calls[1][0]).toBe('/api/auth/me');
    expect(fetcher.mock.calls[1][1].headers.Authorization).toBe(`Bearer ${token}`);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it('shows bad credentials and clears the password',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json({detail:'Invalid username or password'},401)));mount();await signIn();
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password');
    expect(screen.getByLabelText('Password')).toHaveValue('');
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });
  it('keeps workspace hidden and shows loading until /me completes',async()=>{
    let finish;
    vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(json({access_token:jwt(),token_type:'bearer'})).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})));
    mount();await signIn();
    expect(screen.getByRole('button',{name:'Signing in…'})).toBeDisabled();
    expect(screen.getByText('Verifying your identity…')).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    await act(async()=>finish(json({user_id:id,role:'admin'})));
    expect(await screen.findByText('Signed in successfully.')).toBeInTheDocument();
  });
  it.each([{user_id:id,role:'dc_viewer'},{user_id:'invalid',role:'admin'}])('rejects invalid /me identity %j',async(identity)=>{
    mockLogin('admin',identity);mount();await signIn();
    expect(await screen.findByRole('alert')).toHaveTextContent('unsupported user identity');
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });
  it('handles an expired /me response without exposing the workspace',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(json({access_token:jwt(),token_type:'bearer'})).mockResolvedValueOnce(json({detail:'Invalid or expired bearer token'},401)));
    mount();await signIn();expect(await screen.findByRole('alert')).toHaveTextContent('Invalid or expired bearer token');
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });
  it.each(['dispute_associate','compliance_manager','admin'])('renders supported navigation for %s and logs out',async(role)=>{
    mockLogin(role);mount();const user=await signIn();
    const nav=await screen.findByRole('navigation',{name:'Workspace'});
    expect(nav).toHaveTextContent('Investigations');expect(nav).toHaveTextContent('Fine Records');
    await user.click(screen.getByRole('link',{name:/Fine Records/}));
    expect(screen.getByRole('heading',{level:1,name:'Fine Records'})).toBeInTheDocument();
    await user.click(screen.getByRole('button',{name:'Sign out'}));
    expect(await screen.findByRole('heading',{name:'Welcome back'})).toBeInTheDocument();
    expect(screen.getByText('You have signed out.')).toBeInTheDocument();
  });
  it('renders not-found and forbidden pages inside authenticated shell',async()=>{
    mockLogin();const router=mount();await signIn();await screen.findByRole('navigation');
    await act(async()=>router.navigate('/missing'));
    expect(screen.getByRole('heading',{name:'Page not found'})).toBeInTheDocument();
    await act(async()=>router.navigate('/forbidden'));
    expect(screen.getByRole('heading',{name:'Access restricted'})).toBeInTheDocument();
  });
  it('redirects denied roles to forbidden without rendering restricted content',async()=>{
    mockLogin();render(<MemoryRouter initialEntries={['/login']}><AuthProvider><Routes><Route path="login" element={<Login/>}/><Route element={<RequireAuth roles={['compliance_manager']}/>}><Route path="cases" element={<h1>Restricted manager content</h1>}/></Route><Route path="forbidden" element={<h1>Forbidden destination</h1>}/></Routes></AuthProvider></MemoryRouter>);
    await signIn();expect(await screen.findByRole('heading',{name:'Forbidden destination'})).toBeInTheDocument();
    expect(screen.queryByText('Restricted manager content')).not.toBeInTheDocument();
  });
  it('expires an authenticated session on the token deadline',async()=>{
    const timer=vi.spyOn(globalThis,'setTimeout');
    try {
      mockLogin();mount();await signIn();await screen.findByRole('navigation');
      const scheduled=timer.mock.calls.find(([,delay])=>delay > 1700000 && delay <= 1800000);
      expect(scheduled).toBeDefined();
      await act(async()=>scheduled[0]());
      expect(screen.getByRole('heading',{name:'Welcome back'})).toBeInTheDocument();
      expect(screen.getByText('Your session expired. Please sign in again.')).toBeInTheDocument();
    } finally { timer.mockRestore(); }
  });
});

describe('API boundaries',()=>{
  it.each([
    [{error:{code:'conflict',message:'Case changed'}},409,'Case changed'],
    [{detail:'Agent unavailable'},503,'Agent unavailable'],
    [{detail:[{msg:'required'}]},422,'Request data is invalid'],
    [{},403,'permission'],
  ])('normalizes error %j',async(body,status,message)=>{
    const client=createApiClient({fetchImpl:async()=>json(body,status)});
    await expect(client('/api/domain/v1/fine-records')).rejects.toThrow(message);
  });
  it('invalidates 401 sessions, but preserves them on 403',async()=>{
    const expired=vi.fn();const client=createApiClient({getToken:()=> 'token',onUnauthorized:expired,fetchImpl:async()=>json({},401)});
    await expect(client('/api/auth/me')).rejects.toMatchObject({status:401});expect(expired).toHaveBeenCalledOnce();
    const forbidden=createApiClient({getToken:()=> 'token',onUnauthorized:expired,fetchImpl:async()=>json({},403)});
    await expect(forbidden('/api/domain/v1/test')).rejects.toMatchObject({status:403});expect(expired).toHaveBeenCalledOnce();
  });
  it('handles network failures, non-JSON errors and malformed success',async()=>{
    await expect(createApiClient({fetchImpl:async()=>{throw new Error('sensitive URL');}})('/api/auth/me')).rejects.toThrow('Unable to reach');
    await expect(createApiClient({fetchImpl:async()=>new Response('upstream', {status:502})})('/api/auth/me')).rejects.toThrow('request failed');
    await expect(createApiClient({fetchImpl:async()=>new Response('html')})('/api/auth/me')).rejects.toThrow('invalid response');
  });
  it('validates identity and token expiry without trusting token roles',()=>{
    expect(()=>tokenExpiry('broken')).toThrow();expect(()=>tokenExpiry(jwt(1))).toThrow();
    expect(validateIdentity({user_id:id,role:'admin'})).toEqual({user_id:id,role:'admin'});
  });
  it('renders reusable empty/loading/error states and retry action',async()=>{
    const retry=vi.fn();render(<><EmptyState title="No records">Nothing yet.</EmptyState><Loading/><ErrorState message="Failed to load" onRetry={retry}/></>);
    expect(screen.getByRole('status')).toHaveTextContent('Loading');expect(screen.getByRole('heading',{name:'No records'})).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button',{name:'Try again'}));expect(retry).toHaveBeenCalledOnce();
  });
});
