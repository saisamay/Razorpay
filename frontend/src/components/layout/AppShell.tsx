import React from 'react';
import { Header } from './Header';
import { Sidebar } from './Sidebar';

export interface AppShellProps {
  currentPath: string;
  onNavigate: (path: string) => void;
  merchantId: string;
  onMerchantIdChange: (newId: string) => void;
  children: React.ReactNode;
}

export const AppShell: React.FC<AppShellProps> = ({
  currentPath,
  onNavigate,
  merchantId,
  onMerchantIdChange,
  children,
}) => {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-dark-900)' }}>
      <Header merchantId={merchantId} onMerchantIdChange={onMerchantIdChange} />
      <div style={{ display: 'flex', flex: 1 }}>
        <Sidebar currentPath={currentPath} onNavigate={onNavigate} />
        <main style={{ flex: 1, padding: '2rem', overflowY: 'auto' }}>
          {children}
        </main>
      </div>
    </div>
  );
};
