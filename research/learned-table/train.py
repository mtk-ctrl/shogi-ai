import numpy as np,scipy.sparse as sp,sys
from sklearn.linear_model import LogisticRegression
pre=sys.argv[1]; C=float(sys.argv[2]); lam=float(sys.argv[3]) if len(sys.argv)>3 else 1.0
X=sp.load_npz(pre+'_X.npz'); m=np.load(pre+'_m.npz'); mat=m['mat']/1000.0; stm=m['stm']; y=m['y']; gid=m['gid']; sc=m['sc']
soft=lam/(1+np.exp(-sc/1850.0))+(1-lam)*y
D=sp.hstack([sp.csr_matrix(np.c_[mat,stm]),X]).tocsr()
def fit(D,t,C):
    DD=sp.vstack([D,D]).tocsr(); yy=np.r_[np.ones(len(t)),np.zeros(len(t))]; ww=np.r_[t,1-t]
    clf=LogisticRegression(C=C,fit_intercept=False,solver='lbfgs',max_iter=500); clf.fit(DD,yy,sample_weight=ww); return clf
def ll(p,t): p=np.clip(p,1e-6,1-1e-6); return -np.mean(t*np.log(p)+(1-t)*np.log(1-p))
folds=gid%5
for name,cols,c in (('material+stm',slice(0,2),100),('+table',slice(0,D.shape[1]),C)):
    a=[];b=[];r=[]
    for k in range(5):
        tr=folds!=k; te=~tr
        clf=fit(D[tr][:,cols],soft[tr],c); p=clf.predict_proba(D[te][:,cols])[:,1]
        a.append(ll(p,y[te])); b.append(ll(p,soft[te]))
        z=clf.decision_function(D[te][:,cols]); r.append(np.corrcoef(z,sc[te])[0,1])
    print(name,'heldout: outcome logloss %.4f  soft logloss %.4f  corr with search score %.3f'%(np.mean(a),np.mean(b),np.mean(r)),flush=True)
# reference: the search score itself as predictor of the outcome
p=1/(1+np.exp(-sc/1850.0)); print('search score itself: outcome logloss %.4f'%ll(p,y))
clf=fit(D,soft,C); w=clf.coef_[0]; a=w[0]/1000.0
print('logit per 100cp',a*100,'stm cp',w[1]/a); tab=w[2:]/a; np.save(pre+'_table_cp.npy',tab); np.save(pre+'_stm_cp.npy',np.array([w[1]/a]))
print('table cp: abs mean %.1f, p99 %.1f, max %.1f'%(np.abs(tab).mean(),np.percentile(np.abs(tab),99),np.abs(tab).max()))
