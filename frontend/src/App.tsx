import React, { useState } from 'react';
import { AppShell } from './components/layout/AppShell';
import { RecoveryControlCenter } from './pages/RecoveryControlCenter';
import { RecoveryCaseExplorer } from './pages/RecoveryCaseExplorer';
import { CaseDetail } from './pages/CaseDetail';
import { Experiments } from './pages/Experiments';
import { Operations } from './pages/Operations';
import { Governance } from './pages/Governance';
import { Evidence } from './pages/Evidence';

export const App: React.FC = () => {
  const [currentPath, setCurrentPath] = useState<string>(
    typeof window !== 'undefined' && window.location.pathname ? window.location.pathname : '/'
  );
  const [merchantId, setMerchantId] = useState<string>('merchant_123');

  const navigate = (path: string) => {
    setCurrentPath(path);
    if (typeof window !== 'undefined') {
      window.history.pushState({}, '', path);
    }
  };

  const renderCurrentPage = () => {
    if (currentPath === '/') {
      return (
        <RecoveryControlCenter
          merchantId={merchantId}
          onNavigateToCases={() => navigate('/cases')}
        />
      );
    }

    if (currentPath === '/cases') {
      return (
        <RecoveryCaseExplorer
          merchantId={merchantId}
          onSelectCase={(caseId) => navigate(`/cases/${caseId}`)}
        />
      );
    }

    if (currentPath.startsWith('/cases/')) {
      const caseId = currentPath.replace('/cases/', '');
      return (
        <CaseDetail
          caseId={caseId}
          merchantId={merchantId}
          onBackToCases={() => navigate('/cases')}
        />
      );
    }

    switch (currentPath) {
      case '/experiments':
        return <Experiments merchantId={merchantId} />;
      case '/operations':
        return (
          <Operations
            merchantId={merchantId}
            onSelectCase={(caseId) => navigate(`/cases/${caseId}`)}
          />
        );
      case '/governance':
        return <Governance merchantId={merchantId} />;
      case '/evidence':
        return <Evidence merchantId={merchantId} onNavigatePage={(path) => navigate(path)} />;
      default:
        return (
          <RecoveryControlCenter
            merchantId={merchantId}
            onNavigateToCases={() => navigate('/cases')}
          />
        );
    }
  };

  const navPath = currentPath.startsWith('/cases/') ? '/cases' : currentPath;

  return (
    <AppShell
      currentPath={navPath}
      onNavigate={(path) => navigate(path)}
      merchantId={merchantId}
      onMerchantIdChange={(newId) => setMerchantId(newId)}
    >
      {renderCurrentPage()}
    </AppShell>
  );
};

export default App;
