import React from 'react';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { ConnectionState } from '../../types';

interface LayoutProps {
  currentTab: string;
  onSelectTab: (tab: string) => void;
  connectionState: ConnectionState;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({
  currentTab,
  onSelectTab,
  connectionState,
  title,
  subtitle,
  children,
}) => {
  return (
    <div className="app-container">
      <Sidebar
        currentTab={currentTab}
        onSelectTab={onSelectTab}
        connectionState={connectionState}
      />
      <div className="main-content">
        <Header title={title} subtitle={subtitle} />
        <main className="page-container">{children}</main>
      </div>
    </div>
  );
};
