(() => {
  const qs = (selector, scope = document) => scope.querySelector(selector);
  const qsa = (selector, scope = document) => [...scope.querySelectorAll(selector)];

  const page = document.body.dataset.page || 'overview';
  const navigation = [
    ['overview', 'index.html', '总览', '<path d="M4 13h6V4H4v9Zm0 7h6v-4H4v4Zm10 0h6v-9h-6v9Zm0-16v4h6V4h-6Z"/>'],
    ['plan', 'trade-plan.html', '计划', '<path d="M6 3v3m12-3v3M4 9h16M5 5h14v15H4V6a1 1 0 0 1 1-1Z"/>'],
    ['account', 'account.html', '账户', '<path d="M4 7h16v12H4zM7 7V5h10v2M8 13h5"/>'],
    ['execution', 'execution.html', '复盘', '<path d="M5 4h14v16H5zM8 9h8M8 13h5M8 17h7"/>'],
    ['research', 'research.html', '研究', '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 0-3-3V4Z"/><path d="M8 8h7M8 12h6"/>'],
    ['system', 'system.html', '系统', '<circle cx="12" cy="12" r="3"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/>']
  ];
  const sidebarHost = qs('[data-app-sidebar]');
  if (sidebarHost) {
    sidebarHost.outerHTML = `<aside class="sidebar" data-od-id="desktop-sidebar">
      <a class="brand" href="index.html" data-od-id="brand-home-link"><span class="brand-mark">QL</span><span>Quant Ledger</span></a>
      <div class="nav-group"><p class="nav-label">交易工作台</p><nav class="side-nav" aria-label="主导航" data-od-id="desktop-primary-nav">
        ${navigation.map(([id, href, label, icon]) => `<a class="nav-link${page === id ? ' active' : ''}" href="${href}"${page === id ? ' aria-current="page"' : ''}><svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">${icon}</svg>${id === 'plan' ? '交易计划' : id === 'execution' ? '执行复盘' : id === 'research' ? '研究库' : id === 'system' ? '系统状态' : label}</a>`).join('')}
      </nav></div>
      <div class="sidebar-foot" data-od-id="sidebar-system-summary"><div class="system-mini"><span class="status-dot"></span><strong>系统正常</strong></div><small>数据更新至 15:35:12</small></div>
    </aside>`;
  }
  const mobileNavHost = qs('[data-app-mobile-nav]');
  if (mobileNavHost) {
    mobileNavHost.outerHTML = `<nav class="mobile-nav" aria-label="移动端主导航" data-od-id="mobile-primary-nav">
      ${navigation.map(([id, href, label, icon]) => `<a class="${page === id ? 'active' : ''}" href="${href}"${page === id ? ' aria-current="page"' : ''}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor">${icon}</svg>${label}</a>`).join('')}
    </nav>`;
  }

  const toast = qs('[data-toast]');
  let toastTimer;
  const showToast = (message) => {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2200);
  };

  const tradingDates = ['2026-07-10', '2026-07-13', '2026-07-14'];
  let dateIndex = tradingDates.length - 1;
  const updateDate = () => {
    qsa('[data-current-date]').forEach((node) => {
      node.textContent = tradingDates[dateIndex];
      node.setAttribute('datetime', tradingDates[dateIndex]);
    });
  };
  qsa('[data-date-step]').forEach((button) => {
    button.addEventListener('click', () => {
      const step = Number(button.dataset.dateStep);
      const next = Math.max(0, Math.min(tradingDates.length - 1, dateIndex + step));
      if (next === dateIndex) {
        showToast(step > 0 ? '已经是最新交易日' : '没有更早的模拟记录');
        return;
      }
      dateIndex = next;
      updateDate();
      showToast(`已切换到 ${tradingDates[dateIndex]} 的模拟快照`);
    });
  });

  const closeDrawer = (overlay) => {
    if (!overlay) return;
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('drawer-open');
  };
  const stockProfiles = {
    '300750': { name: '宁德时代', action: '买入', target: '10% → 14%', qty: '200 股', reason: '盈利质量分位由 68% 升至 84%，20 日动量重新转正；成长行业风险预算仍有空间。', condition: '若集合竞价高开超过 2.5%，或开盘 15 分钟成交额低于同期中位数 60%，取消买入。', quality: '84% 分位', momentum: '+6.2%', volatility: '17.4%', contribution: '+0.18', order: '分两笔等量限价买入；首笔不早于 09:45，价格偏离决策价不得超过 0.8%。', exit: '盈利质量分位跌破 65%，或 20 日波动率超过 24% 时降回基准仓位。', holdingQty: '1,200 股', market: '¥301,440', cost: '¥238.40', return: '+5.37%', strategy: '多因子中频轮动 v3.4。当前质量、动量信号有效，明日计划增持。', risk: '28.1%', correlation: '0.62' },
    '601318': { name: '中国平安', action: '买入', target: '8% → 11%', qty: '600 股', reason: '价值分位升至 88%，保险行业风险预算释放，低波动特征有助于平衡组合。', condition: '若开盘跳空超过 1.8%，或金融板块成交宽度低于 45%，取消买入。', quality: '71% 分位', momentum: '+2.8%', volatility: '13.1%', contribution: '+0.12', order: '10:00 后分两笔限价买入，不主动追过决策价 0.6%。', exit: '价值分位跌破 65%，或行业风险预算收紧时恢复原仓位。', holdingQty: '5,600 股', market: '¥266,392', cost: '¥48.12', return: '-1.14%', strategy: '低波动价值子策略。当前估值信号有效，价格动量仍偏弱。', risk: '18.7%', correlation: '0.54' },
    '300308': { name: '中际旭创', action: '卖出', target: '12% → 8%', qty: '400 股', reason: '20 日波动率超过阈值，光通信方向的组合风险贡献偏高，优先降低集中度。', condition: '若尾盘价格偏离决策价超过 10bp，不追价并保留未成交仓位。', quality: '76% 分位', momentum: '+9.4%', volatility: '24.8%', contribution: '-0.09', order: '14:30 后分批卖出；价格偏离决策价超过 10bp 时撤单。', exit: '风险贡献回落至 20% 以下后，再评估是否恢复目标仓位。', holdingQty: '1,000 股', market: '¥198,600', cost: '¥188.20', return: '+5.53%', strategy: '成长动量子策略。信号仍为正，但组合风险贡献触及提醒线。', risk: '26.8%', correlation: '0.68' },
    '600519': { name: '贵州茅台', action: '卖出', target: '18% → 15%', qty: '100 股', reason: '单票仓位接近 20% 上限，主动释放现金缓冲，不代表基本面信号转负。', condition: '若开盘低开超过 2.0%，延后至 10:15 再评估，不在恐慌区间卖出。', quality: '82% 分位', momentum: '+1.6%', volatility: '12.6%', contribution: '+0.04', order: '10:15 后一次限价卖出，优先控制成交冲击。', exit: '减仓后维持 15% 核心仓位，除非质量分位跌破 60%。', holdingQty: '150 股', market: '¥233,880', cost: '¥1,508.00', return: '+3.40%', strategy: '盈利质量核心仓。信号稳定，本次仅执行集中度约束。', risk: '16.4%', correlation: '0.49' }
  };
  qsa('[data-drawer-target]').forEach((button) => {
    button.addEventListener('click', () => {
      const overlay = document.getElementById(button.dataset.drawerTarget);
      if (!overlay) return;
      const profile = stockProfiles[button.dataset.stockCode];
      if (profile) {
        qsa('[data-stock-field]', overlay).forEach((node) => {
          const key = node.dataset.stockField;
          const value = key === 'code' ? button.dataset.stockCode : profile[key];
          if (value !== undefined) node.textContent = value;
          if (key === 'action') {
            node.classList.toggle('action-buy', profile.action === '买入');
            node.classList.toggle('action-sell', profile.action === '卖出');
          }
          if (key === 'return') {
            node.classList.toggle('positive', profile.return.startsWith('+'));
            node.classList.toggle('negative', profile.return.startsWith('-'));
          }
        });
      }
      overlay.classList.add('open');
      overlay.setAttribute('aria-hidden', 'false');
      document.body.classList.add('drawer-open');
      qs('[data-drawer-close]', overlay)?.focus();
    });
  });
  qsa('[data-drawer-close]').forEach((button) => {
    button.addEventListener('click', () => closeDrawer(button.closest('.drawer-overlay')));
  });
  qsa('.drawer-overlay').forEach((overlay) => {
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) closeDrawer(overlay);
    });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeDrawer(qs('.drawer-overlay.open'));
  });

  qsa('[data-filter-group]').forEach((group) => {
    const targetSelector = group.dataset.filterTarget;
    const rows = targetSelector ? qsa(targetSelector) : [];
    qsa('[data-filter]', group).forEach((button) => {
      button.addEventListener('click', () => {
        qsa('[data-filter]', group).forEach((item) => item.classList.remove('active'));
        button.classList.add('active');
        const value = button.dataset.filter;
        rows.forEach((row) => {
          row.hidden = value !== 'all' && row.dataset.kind !== value && row.dataset.status !== value;
        });
      });
    });
  });

  const reportSearch = qs('[data-report-search]');
  const reportRows = qsa('[data-report-row]');
  const reportEmpty = qs('[data-report-empty]');
  const reportCategoryGroup = qs('[data-report-categories]');
  let reportCategory = 'all';
  const filterReports = () => {
    const query = reportSearch?.value.trim().toLowerCase() || '';
    let visible = 0;
    reportRows.forEach((row) => {
      const matchQuery = row.textContent.toLowerCase().includes(query);
      const matchCategory = reportCategory === 'all' || row.dataset.category === reportCategory;
      row.classList.toggle('hidden', !(matchQuery && matchCategory));
      if (matchQuery && matchCategory) visible += 1;
    });
    reportEmpty?.classList.toggle('show', visible === 0);
  };
  reportSearch?.addEventListener('input', filterReports);
  qsa('[data-category]', reportCategoryGroup || document).forEach((button) => {
    button.addEventListener('click', () => {
      qsa('[data-category]', reportCategoryGroup).forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      reportCategory = button.dataset.category;
      filterReports();
    });
  });

  qsa('[data-ack]').forEach((button) => {
    button.addEventListener('click', () => {
      const entry = button.closest('[data-log-entry]');
      if (!entry || entry.classList.contains('resolved')) return;
      entry.classList.add('resolved');
      entry.dataset.status = 'resolved';
      button.textContent = '已确认';
      button.disabled = true;
      const countNode = qs('[data-open-issue-count]');
      if (countNode) {
        const nextCount = Math.max(0, Number(countNode.textContent) - 1);
        countNode.textContent = String(nextCount);
      }
      showToast('异常已标记为已确认');
    });
  });

  qsa('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
      const value = button.dataset.copy;
      try {
        await navigator.clipboard.writeText(value);
        showToast(`已复制：${value}`);
      } catch {
        showToast('当前预览环境不支持复制');
      }
    });
  });

  qsa('[data-toggle-details]').forEach((button) => {
    button.addEventListener('click', () => {
      const target = document.getElementById(button.dataset.toggleDetails);
      if (!target) return;
      const hidden = target.hidden;
      target.hidden = !hidden;
      button.textContent = hidden ? '收起日志' : '查看日志';
      button.setAttribute('aria-expanded', String(hidden));
    });
  });

  qsa('[data-download]').forEach((button) => {
    button.addEventListener('click', () => showToast('模拟导出已生成，真实接入时将下载 CSV'));
  });

  updateDate();
})();
