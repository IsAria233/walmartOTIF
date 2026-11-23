import {useEffect, useReducer, useState} from 'react';
import {useAuth} from '../auth/AuthContext';
import {validatePage} from '../api/domain';

// A request key hides previous data immediately; cleanup also guards against
// responses from servers/mocks that ignore AbortSignal.
export default function useRead(path, paginated = true, {keepPrevious = false, refreshKey = 0} = {}) {
  const {client} = useAuth();
  const [revision, refresh] = useReducer(value => value + 1, 0);
  const key = `${path}:${revision}:${refreshKey}`;
  const [result, setResult] = useState(null);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let current = true;
    client(path, {signal: controller.signal})
      .then(data => paginated ? validatePage(data) : data)
      .then(data => { if (current) setResult({key, path, data}); })
      .catch(error => { if (current && error.name !== 'AbortError') setResult(previous => ({key, path, error, data: keepPrevious && previous?.path === path ? previous.data : null})); });
    return () => { current = false; controller.abort(); };
  }, [client, path, paginated, key, keepPrevious]);
  return {data: result?.key === key || (keepPrevious && result?.path === path) ? result.data : null, error: result?.key === key ? result.error : null, loading: !!path && result?.key !== key, refresh, revision};
}
