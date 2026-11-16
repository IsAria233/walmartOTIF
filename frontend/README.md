# frontend

React + React Router, served by Nginx.

Scaffold the app in this folder (keeps Dockerfile and nginx.conf):

    npm create vite@latest . -- --template react
    npm install react-router-dom

Pages: login, investigation queue, line detail (evidence, findings, approve/reject),
manager approvals, pre-invoice flags.

Then start it with the rest of the stack:

    docker compose --profile frontend up --build
